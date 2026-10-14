import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const pluginRoot = path.resolve(__dirname, "../..");
const skillsDir = path.join(pluginRoot, "skills");
const sessionStartHook = path.join(pluginRoot, "hooks", "session_start.sh");
const statusHook = path.join(pluginRoot, "hooks", "jj_status.py");

const MUTATING_TOOLS = new Set([
  "shell",
  "write",
  "edit",
  "patch",
  "bash",
  "apply_patch",
]);

function extractAndStripFrontmatter(content) {
  const match = content.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/);
  if (!match) return { frontmatter: {}, content };

  const frontmatterStr = match[1];
  const body = match[2];
  const frontmatter = {};
  let lastKey = null;

  for (const rawLine of frontmatterStr.split("\n")) {
    const line = rawLine.replace(/\r$/, "");
    const colonIdx = line.indexOf(":");
    if (colonIdx > 0 && !/^\s/.test(line)) {
      const key = line.slice(0, colonIdx).trim();
      const value = line.slice(colonIdx + 1).trim();
      frontmatter[key] = /^(>[+-]?|\|[+-]?)$/.test(value) ? "" : value;
      lastKey = key;
    } else if (lastKey !== null && line.trim() !== "") {
      frontmatter[lastKey] = `${frontmatter[lastKey]} ${line.trim()}`.trim();
    }
  }

  for (const key of Object.keys(frontmatter)) {
    frontmatter[key] = frontmatter[key].replace(/^(["'])([\s\S]*)\1$/, "$2");
  }

  return { frontmatter, content: body };
}

function loadSkills() {
  const skills = [];
  if (!fs.existsSync(skillsDir)) return skills;
  for (const entry of fs.readdirSync(skillsDir, { withFileTypes: true })) {
    if (!entry.isDirectory() || entry.name.startsWith(".")) continue;
    const skillPath = path.join(skillsDir, entry.name, "SKILL.md");
    if (!fs.existsSync(skillPath)) continue;
    const { frontmatter, content } = extractAndStripFrontmatter(
      fs.readFileSync(skillPath, "utf8"),
    );
    skills.push({
      id: entry.name,
      name: frontmatter.name || entry.name,
      ...(frontmatter.description ? { description: frontmatter.description } : {}),
      path: skillPath,
      content,
    });
  }
  return skills;
}

function runCommand(cmd, args, payload, cwd) {
  try {
    const res = spawnSync(cmd, args, {
      cwd,
      input: JSON.stringify(payload),
      encoding: "utf8",
      timeout: 10_000,
    });
    return res.status === 0 && typeof res.stdout === "string" ? res.stdout.trim() : "";
  } catch {
    return "";
  }
}

function resolveToolCwd(input, fallbackCwd) {
  if (input && typeof input === "object") {
    if (typeof input.workdir === "string" && input.workdir) {
      return path.resolve(fallbackCwd, input.workdir);
    }
    if (typeof input.path === "string" && input.path) {
      return path.dirname(path.resolve(fallbackCwd, input.path));
    }
  }
  return fallbackCwd;
}

export const JjSenseiPlugin = async ({ directory }) => {
  const cwd = directory || process.cwd();
  const orientedSessions = new Set();

  return {
    config: async (config) => {
      if (Array.isArray(config.skills)) return;
      config.skills = config.skills || {};
      config.skills.paths = config.skills.paths || [];
      if (!config.skills.paths.includes(skillsDir)) {
        config.skills.paths.push(skillsDir);
      }
    },
    "tool.execute.after": async (input) => {
      if (!input || !MUTATING_TOOLS.has(input.tool)) return;
      runCommand(
        "python3",
        [statusHook],
        {
          hook_event_name: "PostToolUse",
          session_id: input.sessionID || "opencode",
          cwd,
        },
        cwd,
      );
    },
    "experimental.chat.system.transform": async (input, output) => {
      const preamble = runCommand(
        "bash",
        [sessionStartHook],
        { hook_event_name: "SessionStart", cwd },
        cwd,
      );
      if (!preamble) return;
      const sessionID = input?.sessionID || "opencode";
      let statusLine = "";
      if (!orientedSessions.has(sessionID)) {
        orientedSessions.add(sessionID);
        statusLine = runCommand(
          "python3",
          [statusHook],
          { hook_event_name: "SessionStart", session_id: sessionID, cwd },
          cwd,
        );
      }
      output.system.push(statusLine ? `${preamble}\n${statusLine}` : preamble);
    },
  };
};

async function setup(ctx) {
  if (
    !ctx ||
    !ctx.skill ||
    typeof ctx.skill.transform !== "function" ||
    !ctx.session ||
    typeof ctx.session.hook !== "function"
  ) {
    return;
  }

  const defaultCwd = ctx.location?.directory || process.cwd();
  const orientedSessions = new Set();
  const pendingStatus = new Map();

  try {
    const skills = loadSkills();
    await ctx.skill.transform((draft) => {
      for (const skill of skills) {
        try {
          draft.add(skill);
        } catch (err) {
          console.error(`[jj-sensei] skill "${skill.id}" rejected by host:`, err);
        }
      }
    });
  } catch (err) {
    console.error("[jj-sensei] skill registration failed:", err);
  }

  if (ctx.tool && typeof ctx.tool.hook === "function") {
    try {
      await ctx.tool.hook("execute.after", (event) => {
        try {
          if (!event || !MUTATING_TOOLS.has(event.tool)) return;
          const toolCwd = resolveToolCwd(event.input, defaultCwd);
          const out = runCommand(
            "python3",
            [statusHook],
            {
              hook_event_name: "PostToolUse",
              session_id: event.sessionID || "opencode",
              cwd: toolCwd,
            },
            defaultCwd,
          );
          if (!out) return;
          const parsed = JSON.parse(out);
          const line = parsed?.hookSpecificOutput?.additionalContext;
          if (typeof line === "string" && line) {
            pendingStatus.set(event.sessionID, line);
          }
        } catch {
          // Never fail tool execution on hook errors.
        }
      });
    } catch (err) {
      console.error("[jj-sensei] tool hook registration failed:", err);
    }
  }

  try {
    await ctx.session.hook("context", (event) => {
      try {
        const preamble = runCommand(
          "bash",
          [sessionStartHook],
          { hook_event_name: "SessionStart", cwd: defaultCwd },
          defaultCwd,
        );
        if (!preamble) return;

        const sessionID = event.sessionID || "opencode";
        if (!orientedSessions.has(sessionID)) {
          orientedSessions.add(sessionID);
          const initial = runCommand(
            "python3",
            [statusHook],
            { hook_event_name: "SessionStart", session_id: sessionID, cwd: defaultCwd },
            defaultCwd,
          );
          if (initial) {
            pendingStatus.set(sessionID, initial);
          }
        }

        const statusLine = pendingStatus.get(sessionID);
        pendingStatus.delete(sessionID);

        event.system.push({
          type: "text",
          text: statusLine ? `${preamble}\n${statusLine}` : preamble,
        });
      } catch (err) {
        console.error("[jj-sensei] context hook failed:", err);
      }
    });
  } catch (err) {
    console.error("[jj-sensei] session hook registration failed:", err);
  }
}

export default {
  id: "jj-sensei",
  server: JjSenseiPlugin,
  setup,
};
