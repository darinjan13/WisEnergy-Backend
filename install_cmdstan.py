# install_cmdstan.py
import cmdstanpy
import os
import sys


def install():
    if cmdstanpy.cmdstan_path():
        print(f"CmdStan already at: {cmdstanpy.cmdstan_path()}")
        return

    print("Installing CmdStan (this may take 1-2 minutes)...")
    try:
        success = cmdstanpy.install_cmdstan(
            version="2.33.1", cores=2, verbose=True  # Compatible with cmdstanpy 1.1.0
        )
        if success:
            print("CmdStan installed successfully!")
        else:
            print("CmdStan install failed.")
            sys.exit(1)
    except Exception as e:
        print(f"CmdStan install error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    install()
