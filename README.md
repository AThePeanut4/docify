# docify

A script to add docstrings to Python type stubs using reflection

## Features

- Uses [LibCST](https://github.com/Instagram/LibCST) to parse and modify the stub file
- Dynamically imports the actual module to get the runtime docstring
- Handles most `sys.version` and `sys.platform` conditional blocks, will only add docstrings to the correct branch
- Able to modify files in-place with `-i` or `--in-place`
- Won't overwrite existing docstrings
- With `-b` or `--builtins-only`, will only add docstrings for modules found in `sys.builtin_module_names` (stdlib modules written in C).
- With `--if-needed`, will only add docstrings if the object's (Python) source code is unavailable. Useful for language servers like [basedpyright](https://github.com/DetachHead/basedpyright) that are able to extract docstrings from source code.

## Installation

Install from [PyPI](https://pypi.org/project/docify/):

```sh
pip install docify

docify
# or
python -m docify
```

Or from [conda-forge](https://anaconda.org/conda-forge/docify):

```sh
conda install conda-forge::docify

docify
# or
python -m docify
```

Or just download and run the script directly:

```sh
# Install dependencies
pip install libcst tqdm  # tqdm is optional, and is only used if not running with -q

python docify.py
# or
python -m docify
# or
chmod +x docify.py
./docify.py
```

## Usage

```
docify [-h] [-V] [-v] [-q] [-b] [--if-needed] (-i | -o OUTPUT_DIR) INPUT_DIR [INPUT_DIR ...]

A script to add docstrings to Python type stubs using reflection

positional arguments:
  INPUT_DIR             directory to read stubs from

options:
  -h, --help            show this help message and exit
  -V, --version         show program's version number and exit
  -v, --verbose         increase verbosity
  -q, --quiet           decrease verbosity
  -b, --builtins-only   only add docstrings to modules found in `sys.builtin_module_names`
  --if-needed           only add a docstring if the object's source code cannot be found
  -i, --in-place        modify stubs in-place
  -o, --output OUTPUT_DIR
                        directory to write modified stubs to
```
