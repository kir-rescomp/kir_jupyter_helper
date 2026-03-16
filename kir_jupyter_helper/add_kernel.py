import os
import sys
import json
import tempfile
import subprocess
import shutil
import typing as T
from pathlib import Path

import defopt
import jupyter_core.paths


WRAPPER_TEMPLATE = """\
#!/usr/bin/env bash

set -e

# start with a clean environment
module purge

# load required modules
{modules_txt}
{exec_txt}
"""

CONDA_TEMPLATE = """\
# load Conda on Mahuika or Maui
if hostname | grep -q "maui"; then
    module load Anaconda3
else
    module load Miniconda3
fi

# isolate conda environment from user's site-packages directory
export PYTHONNOUSERSITE=True

# activate conda environment
source $(conda info --base)/etc/profile.d/conda.sh
conda deactivate  # enforce base environment to be unloaded
conda activate {conda_venv}

# run the kernel
exec python $@
"""

VENV_TEMPLATE = """\
# isolate virtual environment from user's site-packages directory
export PYTHONNOUSERSITE=True

# activate virtual environment
source {venv_activate_script}

# run the kernel
exec python $@
"""

CONTAINER_TEMPLATE = """\
module load Singularity

# isolate container interpreter from user's site-packages directory
export SINGULARITYENV_PYTHONNOUSERSITE=True

# run the kernel inside the container
exec singularity exec -B {runtime_dir} {container_args} {container} python $@
"""


def add_kernel(
    kernel_name: str,
    *module: str,
    conda_path: T.Optional[Path] = None,
    conda_name: T.Optional[str] = None,
    venv: T.Optional[Path] = None,
    container: T.Optional[Path] = None,
    container_args: str = "",
    shared: bool = False,
    account: T.Optional[str] = None,
):
    """Register a new jupyter kernel, with a wrapper script to load NeSI modules

    :param kernel_name: Jupyter kernel name
    :param module: NeSI module(s) to load before running the kernel
    :param conda-path: path to a Conda environment
    :param conda-name: name of a Conda environment
    :param venv: path to a Python virtual environment
    :param container: path to a Singularity container
    :param container_args: additional parameters for 'singularity exec' command
    :param shared: share the kernel with other members of your NeSI project
    :param account: NeSI account for a shared kernel, instead of current job's
    """

    incompatible_options = conda_path, conda_name, venv, container
    if sum(option is not None for option in incompatible_options) >= 2:
        sys.exit(
            "ERROR: --conda-path, --conda-name, --venv and --container options "
            "are not compatible"
        )

    # path to kernel directory
    if shared:
        if account is None:
            account = os.getenv("SLURM_JOB_ACCOUNT", os.getenv("JUPYTER_JOB_ACCOUNT"))
            if account is None:
                sys.exit(
                    "ERROR: cannot determine project to share kernel with, try "
                    "running within a Jupyter terminal or use the --account option"
                )
        print(f"Creating shared kernel for {account}")
        prefix_dir = Path(f"/nesi/project/{account}/.jupyter")
        kernel_dir = prefix_dir / "share/jupyter/kernels/" / kernel_name
    else:
        kernel_dir = Path.home() / ".local/share/jupyter/kernels/" / kernel_name

    # check kernel directory does not already exist
    if kernel_dir.exists():
        sys.exit(f"ERROR: Kernel already exists: {kernel_dir}")

    # create a bash wrapper script
    if len(module) == 0:
        modules_txt = ""
    else:
        modules_txt = "module load " + " ".join(module) + "\n"

        # Python/3.11.6-foss-2023a module does not have ipykernel, warn the
        # user if they are using this module and not using a venv because it
        # could install things into ~/.local that conflict with JupyterLab
        if "Python/3.11.6-foss-2023a" in module and venv is None:
            print(
                "WARNING: ipykernel is not included in "
                "Python/3.11.6-foss-2023a - we recommend using a virtual "
                "enviroment (--venv) or the latest JupyterLab "
                "module from the foss/2023a toolchain instead to avoid "
                "ipykernel being installed under ~/.local (which could cause "
                "problems for JupyterLab)"
            )

    # use a conda environment...
    if conda_name is not None:
        if shared:
            print(
                "Make sure your conda environment is accessible to members of "
                f"{account}"
            )
        exec_txt = CONDA_TEMPLATE.format(conda_venv=conda_name)

    elif conda_path is not None:
        if shared:
            print(
                "Make sure your conda environment is accessible to members of "
                f"{account}"
            )
        conda_path = conda_path.resolve()
        if not conda_path.is_dir():
            sys.exit(
                f"ERROR: --conda-path ({conda_path}) should point to a conda "
                "environment directory"
            )
        exec_txt = CONDA_TEMPLATE.format(conda_venv=conda_path)

    # ...or a virtual environment...
    elif venv is not None:
        if shared:
            print(
                "Make sure your virtual environment is accessible to members of "
                f"{account}"
            )
        venv = venv.resolve()
        if not venv.is_dir():
            sys.exit(
                f"ERROR: --venv ({venv}) should point to a virtual environment "
                "directory"
            )
        venv_activate_script = venv / "bin/activate"
        if not venv_activate_script.exists():
            sys.exit(
                f"ERROR: --venv ({venv}) does not appear to be a virtual "
                "environment (cannot find bin/activate)"
            )
        exec_txt = VENV_TEMPLATE.format(venv_activate_script=venv_activate_script)
        if not any(m.startswith("Python") for m in module):
            print(
                "WARNING: Make sure to specify the appropriate Python module "
                "for your virtual environment."
            )

    # ...or a Singularity container...
    elif container is not None:
        container = container.resolve()
        if shared:
            print("Make sure your container is accessible to members of {account}")
        if not container.is_file():
            sys.exit(
                f"ERROR: --container ({container}) should point to a Singularity "
                "container image file"
            )
        runtime_dir = jupyter_core.paths.jupyter_runtime_dir()
        exec_txt = CONTAINER_TEMPLATE.format(
            container=container, container_args=container_args, runtime_dir=runtime_dir
        )

    # ...or the default python interpreter
    else:
        exec_txt = "# run the kernel\nexec python $@"

    wrapper_script_code = WRAPPER_TEMPLATE.format(
        modules_txt=modules_txt, exec_txt=exec_txt
    )

    # use a temporary file for testing purpose
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as fh:
        fh.write(wrapper_script_code)

    wrapper_script = Path(fh.name)
    wrapper_script.chmod(0o770)

    print("Testing wrapper script")
    try:
        subprocess.run(
            [wrapper_script, "--version"],
            check=True,
            capture_output=True,
            universal_newlines=True,
        )
    except subprocess.CalledProcessError as exc:
        print(exc.stdout)
        print(exc.stderr)
        wrapper_script.unlink()
        sys.exit(
            "ERROR: unable to create wrapper script, check modules and other "
            "options are correct"
        )

    print("Checking & installing ipykernel package in the kernel environment")
    try:
        subprocess.run(
            [wrapper_script, "-m", "pip", "install", "ipykernel"],
            check=True,
            capture_output=True,
            universal_newlines=True,
        )
    except subprocess.CalledProcessError as exc:
        print(exc.stdout)
        print(exc.stderr)
        wrapper_script.unlink()
        sys.exit(
            "ERROR: the ipykernel package could not be installed in the kernel "
            "environment"
        )

    # create a new kernel
    cmdargs = ["python", "-m", "ipykernel", "install", "--name", kernel_name]
    if shared:
        cmdargs.extend(["--prefix", prefix_dir])
    else:
        cmdargs.append("--user")
    print(f"Installing kernel: {' '.join(map(str, cmdargs))}")
    subprocess.run(cmdargs, check=True)

    # add the wrapper script to the kernel dir
    wrapper_script_dest = kernel_dir / "wrapper.bash"
    shutil.move(wrapper_script, wrapper_script_dest)
    print(f"Added wrapper script in {wrapper_script_dest}")

    # modify the kernel description file
    kernel_def = {
        "argv": [
            str(wrapper_script_dest),
            "-m",
            "ipykernel_launcher",
            "-f",
            "{connection_file}",
        ],
        "display_name": kernel_name,
        "language": "python",
    }
    kernel_file = kernel_dir / "kernel.json"
    with kernel_file.open("w") as fd:
        json.dump(kernel_def, fd, indent=4)
    print(f"Updated kernel JSON file {kernel_file}")

    print("\nUse the following command to remove the kernel:")
    print(f"\n    jupyter-kernelspec remove {kernel_name}\n")


def main():
    defopt.run(
        add_kernel,
        short={
            "conda-path": "p",
            "conda-name": "n",
            "venv": "v",
            "shared": "s",
            "container": "c",
            "account": "a",
        },
    )
