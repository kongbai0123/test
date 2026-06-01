import subprocess
import os

def main():
    env = os.environ.copy()
    nvm_dir = os.path.expanduser("~/.nvm")
    node_bin = os.path.join(nvm_dir, "versions/node/v20.20.2/bin")
    env["PATH"] = f"{node_bin}:{env['PATH']}"
    
    print("Starting frontend build via subprocess...")
    # We will use subprocess to run npm run build
    res = subprocess.run(
        ["npm", "run", "build"],
        cwd="/home/user/workspace/nvidia/frontend",
        env=env,
        capture_output=True,
        text=True
    )
    print("STDOUT:")
    print(res.stdout)
    print("STDERR:")
    print(res.stderr)
    print(f"Exit code: {res.returncode}")

if __name__ == "__main__":
    main()
