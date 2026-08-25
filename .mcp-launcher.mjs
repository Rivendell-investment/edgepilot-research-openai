import { spawn } from "node:child_process";

const entry = process.argv[2];
if (!entry) {
  process.stderr.write("EdgePilot Research MCP launcher requires a Python entry point.\n");
  process.exit(2);
}

const candidates = process.platform === "win32"
  ? [["py", ["-3", entry]], ["python", [entry]], ["python3", [entry]]]
  : [["python3", [entry]], ["python", [entry]]];
let activeChild;

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => activeChild?.kill(signal));
}

function start(index) {
  if (index >= candidates.length) {
    process.stderr.write("EdgePilot Research requires Python 3 on PATH to start its local MCP.\n");
    process.exit(127);
  }
  const [command, args] = candidates[index];
  const child = spawn(command, args, { cwd: process.cwd(), env: process.env, stdio: "inherit" });
  activeChild = child;
  child.once("error", (error) => {
    if (error.code === "ENOENT") start(index + 1);
    else {
      process.stderr.write(`EdgePilot Research MCP could not start: ${error.message}\n`);
      process.exit(1);
    }
  });
  child.once("exit", (code, signal) => {
    process.exit(signal ? 1 : (code ?? 1));
  });
}

start(0);
