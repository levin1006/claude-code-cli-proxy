import os
import sys
import urllib.request
import platform
import tarfile
import zipfile
import stat
from pathlib import Path

# --- Configuration ---
MIN_PYTHON_VERSION = (3, 8)
REPO_RAW_URL = "https://raw.githubusercontent.com/levin1006/claude-code-cli-proxy/main"
VERSION = "6.8.24"

INSTALL_DIR = Path.home() / ".cli-proxy"
DIRECTORIES_TO_CREATE = [
    "bash",
    "powershell",
    "python",
    "configs/antigravity",
    "configs/claude",
    "configs/codex",
    "configs/gemini",
]
FILES_TO_DOWNLOAD = {
    "config.yaml": "config.yaml",
    "bash/cc-proxy.sh": "bash/cc-proxy.sh",
    "powershell/cc-proxy.ps1": "powershell/cc-proxy.ps1",
    "python/cc_proxy.py": "python/cc_proxy.py",
}

def check_python_version():
    if sys.version_info < MIN_PYTHON_VERSION:
        print(f"Error: Python {MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]} or higher is required.")
        sys.exit(1)
    print(f"Python version check passed: {sys.version.split(' ')[0]}")

def create_directories():
    for d in DIRECTORIES_TO_CREATE:
        (INSTALL_DIR / d).mkdir(parents=True, exist_ok=True)
    print(f"Created directories under {INSTALL_DIR}")

def download_file(url, target_path):
    print(f"Downloading {url} ...")
    try:
        urllib.request.urlretrieve(url, target_path)
        print(f"  -> Saved to {target_path}")
    except Exception as e:
        print(f"Error downloading {url}: {e}")
        sys.exit(1)

def download_core_files():
    for local_path, repo_path in FILES_TO_DOWNLOAD.items():
        url = f"{REPO_RAW_URL}/{repo_path}"
        target = INSTALL_DIR / local_path
        download_file(url, target)

def download_and_extract_binary():
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "windows":
        filename = f"CLIProxyAPI_{VERSION}_windows_amd64.exe"
        # Download from official releases instead of raw repo content (which is gitignored)
        url = f"https://github.com/router-for-me/CLIProxyAPI/releases/download/v{VERSION}/{filename}"
        target_path = INSTALL_DIR / "cli-proxy-api.exe"
        download_file(url, target_path)
    else:
        # Linux / macOS
        # Assuming we download the tar.gz from official releases or our repo if stored there
        # We use a placeholder URL here, adjust to actual binary download URL
        # For this setup, we'll try to get it from the router-for-me releases or a known URL
        # According to the context: "CLIProxyAPI_6.8.24_linux_amd64.tar.gz"
        filename = f"CLIProxyAPI_{VERSION}_linux_amd64.tar.gz"
        url = f"https://github.com/router-for-me/CLIProxyAPI/releases/download/v{VERSION}/{filename}"
        tar_path = INSTALL_DIR / filename
        
        download_file(url, tar_path)
        
        print(f"Extracting {filename} ...")
        try:
            with tarfile.open(tar_path, "r:gz") as tar:
                # Find the binary in the tar
                for member in tar.getmembers():
                    if "cli-proxy-api" in member.name and not member.isdir():
                        # Extract it directly to INSTALL_DIR
                        member.name = "cli-proxy-api" # Flatten
                        tar.extract(member, path=INSTALL_DIR)
                        break
        except Exception as e:
            print(f"Error extracting binary: {e}")
            sys.exit(1)
        finally:
            if tar_path.exists():
                tar_path.unlink() # Clean up tar file
                
        # Make binary and bash script executable
        binary_path = INSTALL_DIR / "cli-proxy-api"
        bash_script = INSTALL_DIR / "bash/cc-proxy.sh"
        
        if binary_path.exists():
            binary_path.chmod(binary_path.stat().st_mode | stat.S_IEXEC)
        if bash_script.exists():
            bash_script.chmod(bash_script.stat().st_mode | stat.S_IEXEC)
            
        print("Set executable permissions for Linux/macOS binary and scripts.")

def setup_profile():
    system = platform.system().lower()
    
    if system == "windows":
        profile_cmd = f". {INSTALL_DIR}\\powershell\\cc-proxy.ps1\nInstall-CCProxyProfile"
        print("\n--- Setup Profile ---")
        print("To complete setup, run the following in PowerShell to register the profile:")
        print(f"  . {INSTALL_DIR}\\powershell\\cc-proxy.ps1")
        print("  Install-CCProxyProfile")
    else:
        # Linux/macOS
        # Add source line to ~/.bashrc and ~/.zshrc
        source_line = f"source {INSTALL_DIR}/bash/cc-proxy.sh"
        
        for rc_file in [".bashrc", ".zshrc"]:
            rc_path = Path.home() / rc_file
            if rc_path.exists():
                content = rc_path.read_text()
                if source_line not in content:
                    with open(rc_path, "a") as f:
                        f.write(f"\n# Added by cli-proxy installer\n{source_line}\n")
                    print(f"Added source line to ~/{rc_file}")
                else:
                    print(f"Source line already exists in ~/{rc_file}")
                    
        print("\n--- Setup Profile ---")
        print("To apply changes immediately, run:")
        print(f"  source {INSTALL_DIR}/bash/cc-proxy.sh")
        print("Or restart your terminal.")

def main():
    print("Starting cli-proxy-api installation...")
    check_python_version()
    create_directories()
    download_core_files()
    download_and_extract_binary()
    setup_profile()
    
    print("\n✅ Installation complete!")

if __name__ == "__main__":
    main()
