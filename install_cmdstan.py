# install_cmdstan.py
import cmdstanpy
import os
import sys


def main():
    # Safely check if CmdStan is already installed
    try:
        path = cmdstanpy.cmdstan_path()
        if path and os.path.exists(os.path.join(path, "bin", "stanc")):
            print(f"CmdStan already installed at: {path}")
            return
    except ValueError:
        # This is expected if no installation exists
        pass

    print(
        "No CmdStan installation found. Installing CmdStan 2.33.1 (this may take 1-2 minutes)..."
    )
    try:
        success = cmdstanpy.install_cmdstan(
            dir=None,  # Use default location
            version="2.33.1",  # Compatible with cmdstanpy 1.1.0
            cores=2,
            verbose=True,
            progress=True,
            overwrite=False,  # Don't overwrite if exists
        )
        if success:
            print(f"CmdStan installed successfully to: {cmdstanpy.cmdstan_path()}")
        else:
            print("CmdStan installation failed!")
            sys.exit(1)
    except Exception as e:
        print(f"Error during CmdStan installation: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
