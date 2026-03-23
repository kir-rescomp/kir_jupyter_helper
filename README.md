<h2 align="center">KIR Jupyter Helper</h2>

<p align="center">
  <img src="./img/kir_jupyter_helper_logo.png" alt="logo" width="300"/>
</p>

kir-jupyter-helper is a set of command-line tool for assiting Jupyter functions (it supports JupyterLab on both OpenOnDemand or a session opened via `srun` with port-forwarding)

## `kir-add-kernel`

Primary tool of this is `kir-add-kernel`which solves a common frustration on HPC clusters with respect to adding a Jupyter kernel : by default, Jupyter requires `ipykernel` to be installed inside every environment you want to use as a kernel. This is invasive — installing `ipykernel` into a carefully pinned conda environment or virtual environment can silently upgrade or downgrade other packages, breaking reproducibility.

Instead, `kir-add-kernel` registers a lightweight wrapper script as the kernel. The wrapper loads your environment via the module system, conda, venv, or Apptainer — and delegates to 
the `ipykernel` that ships with the cluster's JupyterLab module. Your environment stays untouched.

### How does it work ?

<p align="center">
    <img src="./img/kernel_wrapper_architecture.svg" alt="kernel-wrapper"  width="800"/>
</p>

Normally, registering a Jupyter kernel requires installing `ipykernel` directly into each environment.
On a shared cluster this is problematic — `ipykernel` pulls in a large dependency tree that can silently
upgrade or downgrade other packages, undermining the reproducibility of your analysis environment.
`kir-jupyter-helper/kir-add-kernel` takes a different approach. It registers a small bash wrapper script
as the kernel instead. When JupyterLab launches the kernel, the wrapper activates your environment
(via modules, conda, venv, or Apptainer) and then delegates to the `ipykernel` that already ships with the
cluster's `JupyterLab` module. Your environment is never modified.

An additional benefit is shared kernels: a single registration under your group's `shared` directory makes the kernel available to all group members without each person having to set anything up.
