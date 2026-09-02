import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { basename, dirname, join, parse } from "node:path";

const entry = process.argv[2];
if (!entry) {
  process.stderr.write("EdgePilot Research MCP launcher requires a Python entry point.\n");
  process.exit(2);
}

function hostBundledPython() {
  // When the host app launches us with its bundled Node (for example the Codex
  // runtime at .../dependencies/node/bin/node), prefer the Python that ships in
  // the same runtime bundle over whatever the user PATH happens to resolve.
  let current = dirname(process.execPath);
  const { root } = parse(current);
  while (current !== root) {
    if (basename(current) === "dependencies") {
      const bundled = process.platform === "win32"
        ? [join(current, "python", "python.exe")]
        : [join(current, "python", "bin", "python3"), join(current, "python", "bin", "python")];
      return bundled.find((candidate) => existsSync(candidate)) ?? null;
    }
    current = dirname(current);
  }
  return null;
}

const candidates = process.platform === "win32"
  ? [["py", ["-3", entry]], ["python", [entry]], ["python3", [entry]]]
  : [["python3", [entry]], ["python", [entry]]];
const bundledPython = hostBundledPython();
if (bundledPython) {
  candidates.unshift([bundledPython, [entry]]);
}
const productionEnv = { ...process.env };
delete productionEnv.EDGEPILOT_RESEARCH_HOME;
delete productionEnv.EDGEPILOT_RESEARCH_ORIGIN;
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
  const child = spawn(command, args, { cwd: process.cwd(), env: productionEnv, stdio: "inherit" });
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
