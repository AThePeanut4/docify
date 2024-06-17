# docify

A script to add docstrings to Python type stubs using reflection

## Features

- Uses [LibCST](https://github.com/Instagram/LibCST) to parse and modify the stub file
- Dynamically imports the actual module to get the runtime docstring
- Handles most `sys.version` and `sys.platform` conditional blocks, will only add docstrings to the correct branch
- Able to modify files in-place with `-i` or `--in-place`
- Won't overwrite existing docstrings
- With `-b` or `--builtins-only`, will only add docstrings for modules found in `sys.builtin_module_names` (stdlib modules written in C). Useful for language servers that would otherwise not be able to find docstrings due to there being no source file.

## Requirements

- Python 3.8+
- [LibCST](https://github.com/Instagram/LibCST), and [tqdm](https://github.com/tqdm/tqdm) for a progress bar if running without `-q`

## Usage

```
docify.py [-h] [-v] [-q] [-b] (-i | -o OUTPUT_DIR) INPUT_DIR

A script to add docstrings to Python type stubs using reflection

positional arguments:
  INPUT_DIR             directory to read stubs from

options:
  -h, --help            show this help message and exit
  -v, --verbose         increase verbosity
  -q, --quiet           decrease verbosity
  -b, --builtins-only   only add docstrings to modules found in `sys.builtin_module_names`
  -i, --in-place        modify stubs in-place
  -o OUTPUT_DIR, --output OUTPUT_DIR
                        directory to write modified stubs to
```
