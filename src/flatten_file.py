import argparse
import ast
import sys
import importlib.util
from pathlib import Path
from collections import defaultdict
import subprocess

PROJECT_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = Path(str(PROJECT_ROOT).replace('src', 'sample_project'))  # remove this if you work within src folder
# PROJECT_ROOT = Path('/Users/ovila.lugard/PycharmProjects/workato-flattened-file-generator/sample_project')
print(f"Project source: {PROJECT_ROOT}")
SRC_DIR = PROJECT_ROOT

ENTRYPOINT_1 = SRC_DIR / "main.py"
MAIN_ENTRY_POINTS = [ENTRYPOINT_1]

sys.path.insert(0, str(SRC_DIR))

BUILTIN_MODULES = set(sys.builtin_module_names)

# use this if you need to set up global variable manually of if you want to call any specific statements
HARDCODED_STATEMENTS = """
"""

ON_TOP_FILE_COMMENT = """
\"\"\"
🚨🚨🚨
🚀🚀🚀 This is the Workato Prod File GENERATED 🚀🚀🚀
PLEASE DO NOT MODIFY THIS FILE:
MODIFY THE SOURCES FILE INSTEAD (DEV,...), THEN RE-RUN THE SCRIPT GENERATOR.

COPY/PASTE THIS FILE INTO THE PYTHON ACTION WITHIN WORKATO FRAMEWORK

THEN YOU ARE GOOD TO GO, GOOD LUCK BUD
🚨🚨🚨
\"\"\"
"""

ignore_imports = []

main_function_ast = None


def find_main_function(tree):
    """
    Find and return the AST node for the 'main' function in the given AST tree.
    Removes the docstring from the node if present.

    Args:
        tree (ast.Module): The AST of a Python module.

    Returns:
        ast.FunctionDef or None: The AST node of the main function, or None if not found.

    Example:
        tree = ast.parse(open("main.py").read())
        main_node = find_main_function(tree)
    """
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            remove_docstrings(node)
            return node
    return None


def is_builtin_import(module_name: str) -> bool:
    """
    Checks if a given module name corresponds to a built-in Python module.

    Args:
        module_name (str): The name of the module.

    Returns:
        bool: True if the module is built-in, False otherwise.

    Example:
        is_builtin_import("os")  # True
        is_builtin_import("my_custom_module")  # False
    """
    if module_name in BUILTIN_MODULES:
        return True
    try:
        spec = importlib.util.find_spec(module_name)
        if spec and spec.origin == 'built-in':
            return True
    except ModuleNotFoundError:
        return False
    return False


def parse_file(filepath: Path) -> ast.Module:
    """
    Parse a Python file and return its AST.

    Args:
        filepath (Path): The path to the Python file.

    Returns:
        ast.Module: The parsed AST.

    Example:
        tree = parse_file(Path("script.py"))
    """
    with open(filepath, 'r') as f:
        return ast.parse(f.read(), filename=str(filepath))


def extract_imports(tree: ast.AST):
    """
    Extract all import statements (import/import from) from an AST tree.

    Args:
        tree (ast.AST): The AST of the Python code.

    Returns:
        list: A list of ast.Import and ast.ImportFrom nodes.

    Example:
        imports = extract_imports(tree)
    """
    imports = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append(node)
    return imports


def extract_all_defs(tree: ast.AST):
    """
    Extract all function, async function, class, and global assignment definitions from an AST.

    Args:
        tree (ast.AST): The AST of the Python code.

    Returns:
        list: List of ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, and ast.Assign nodes.

    Example:
        defs = extract_all_defs(tree)
    """
    defs = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defs.append(node)
        elif isinstance(node, ast.Assign):
            defs.append(node)
    return defs


def find_used_names(tree: ast.AST):
    """
    Traverse the AST tree and find all names (variables, functions, etc.) used in the code.

    Args:`
        tree (ast.AST): The AST of the Python code.

    Returns:
        set: Set of all used names as strings.

    Example:
        used = find_used_names(tree)
    """
    class UsedNameVisitor(ast.NodeVisitor):
        def __init__(self):
            self.names = set()

        def visit_Name(self, node):
            self.names.add(node.id)

        def visit_Attribute(self, node):
            # Only collect base name (e.g., 'SnowflakeActionsData' from module.SnowflakeActionsData)
            while isinstance(node, ast.Attribute):
                node = node.value
            if isinstance(node, ast.Name):
                self.names.add(node.id)

        def visit_FunctionDef(self, node):
            # Add decorators
            for decorator in node.decorator_list:
                self.visit(decorator)

            # Add type hints in arguments
            for arg in node.args.args + node.args.kwonlyargs:
                if arg.annotation:
                    self.visit(arg.annotation)

            # Add return type hint
            if node.returns:
                self.visit(node.returns)

            self.generic_visit(node)

        def visit_AnnAssign(self, node):
            if node.annotation:
                self.visit(node.annotation)
            if node.value:
                self.visit(node.value)

        def visit_arg(self, node):
            if node.annotation:
                self.visit(node.annotation)

    visitor = UsedNameVisitor()
    visitor.visit(tree)
    return visitor.names


def remove_docstrings(node):
    """
    Recursively remove docstrings from the given AST node (function, class, or module).

    Args:
        node (ast.AST): The AST node to process.

    Example:
        tree = ast.parse(open("file.py").read())
        for node in tree.body:
            remove_docstrings(node)
    """
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        if (node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value,
                                                                            ast.Constant) and isinstance(
                node.body[0].value.value, str)):
            node.body = node.body[1:]
    for child in ast.iter_child_nodes(node):
        remove_docstrings(child)


def get_module_path(module_name: str) -> Path:
    """
    Get the file path of a module within the source directory, if available.

    Args:
        module_name (str): The module name.

    Returns:
        Path or None: The path to the module, or None if not found or outside SRC_DIR.

    Example:
        path = get_module_path("utils")
    """
    try:
        spec = importlib.util.find_spec(module_name)
        if spec and spec.origin and SRC_DIR in Path(spec.origin).parents:
            return Path(spec.origin)
    except Exception:
        return None
    return None


def collect_dependencies(entry_path: Path, preload_paths: list[Path] = None):
    """
    Collect all imports and definitions needed for an entry point, including dependencies.

    Args:
        entry_path (Path): The path of the main entry file.
        preload_paths (list[Path], optional): List of additional files to preload.

    Returns:
        tuple: (all_imports, collected_defs, global_vars)
            - all_imports: set of AST import nodes
            - collected_defs: dict of definitions by name
            - global_vars: list of AST assignment nodes

    Example:
        all_imports, defs, globals = collect_dependencies(Path("main.py"), [Path("utils.py")])
    """
    global main_function_ast
    preload_paths = preload_paths or []

    # Initialize queues and tracking sets
    original_queue = []
    for path in preload_paths:
        if path not in original_queue:
            original_queue.append(path)
    if entry_path not in original_queue:
        original_queue.append(entry_path)

    seen_files = set()
    pending_files = set()  # Track files we've discovered but not processed
    collected_defs = {}
    global_vars = []
    all_imports = set()

    # First process all files in specified order
    for current_path in original_queue:
        # Process the entire file and its dependencies
        process_file(current_path, seen_files, pending_files, collected_defs,
                     global_vars, all_imports)

    # Then process any pending files discovered during first phase
    while pending_files:
        current_path = pending_files.pop()
        if current_path in seen_files:
            continue

        process_file(current_path, seen_files, pending_files, collected_defs,
                     global_vars, all_imports)

    return all_imports, collected_defs, global_vars


def process_file(file_path: Path, seen_files: set, pending_files: set,
                 collected_defs: dict, global_vars: list, all_imports: set):
    """
    Parse and analyze a file, collecting its definitions, global variables, and imports.
    Updates the provided sets/dicts with discovered items.

    Args:
        file_path (Path): The file to process.
        seen_files (set): Set of already processed files.
        pending_files (set): Set to add discovered but unprocessed files.
        collected_defs (dict): Collected definitions (name -> (node, file_path)).
        global_vars (list): List of AST assignment nodes.
        all_imports (set): Set of all AST import nodes.

    Example:
        process_file(Path("main.py"), set(), set(), {}, [], set())
    """
    global main_function_ast

    if file_path in seen_files:
        return

    seen_files.add(file_path)

    # Parse the file
    try:
        tree = parse_file(file_path)
    except Exception as e:
        print(f"🚨 Error parsing {file_path}: {e}")
        exit(f"🚨 Error parsing {file_path}: {e}")

    # Process imports and register dependencies
    file_imports = extract_imports(tree)
    all_imports.update(file_imports)

    # Find all references and used names
    used_names = find_used_names(tree)

    # Check if this is the entry point
    if file_path in MAIN_ENTRY_POINTS:
        main_function_ast = find_main_function(tree)

    # Process all definitions in this file (functions, classes, global vars)
    file_defs = {}
    for node in extract_all_defs(tree):
        node_name = getattr(node, 'name', None)
        if isinstance(node, ast.Assign):  # Global variable assignment
            for target in node.targets:
                if isinstance(target, ast.Name):
                    global_vars.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
            remove_docstrings(node)
            file_defs[node_name] = (node, file_path)

    # Add all definitions from this file to the collected definitions
    collected_defs.update(file_defs)

    # Process imports to discover new files
    for imp in file_imports:
        if isinstance(imp, ast.ImportFrom):
            module = imp.module
            if module and not is_builtin_import(module.split('.')[0]):
                module_path = get_module_path(module)
                if module_path and module_path not in seen_files:
                    pending_files.add(module_path)
        elif isinstance(imp, ast.Import):
            for alias in imp.names:
                mod = alias.name
                if mod and not is_builtin_import(mod.split('.')[0]):
                    module_path = get_module_path(mod)
                    if module_path and module_path not in seen_files:
                        pending_files.add(module_path)


def collect_non_source_imports(imports):
    """
    Collect all imports that are NOT from the source directory and deduplicate them.

    Args:
        imports (list): List of AST import nodes.

    Returns:
        defaultdict: Mapping from module name to set of imported names.

    Example:
        ext_imports = collect_non_source_imports(imports)
    """
    non_source_imports = defaultdict(set)

    # dirty work, TODO: please improve this
    def check_not_from_black_list(imp):
        for alias in imp.names:
            if alias.name in ignore_imports:
                return False
        return True

    for imp in imports:
        if isinstance(imp, ast.ImportFrom):
            # Check if the module is outside of the source directory

            if not is_within_project(imp.module) and check_not_from_black_list(imp):
                non_source_imports[imp.module].update(alias.name for alias in imp.names)
        elif isinstance(imp, ast.Import):
            for alias in imp.names:
                # Add only non-source imports
                if not is_within_project(alias.name):
                    non_source_imports[alias.name].add('*')

    return non_source_imports


def is_within_project(module_name):
    """
    Check if a module is part of the source directory (SRC_DIR).

    Args:
        module_name (str): The module name.

    Returns:
        bool: True if the module is within SRC_DIR, False otherwise.

    Example:
        is_within_project("my_package.utils")  # True if in SRC_DIR
    """
    try:
        # Check if the module is inside the project directory (SRC_DIR)
        spec = importlib.util.find_spec(module_name)
        if spec and spec.origin:
            return SRC_DIR in Path(spec.origin).parents
    except ModuleNotFoundError as e:
        return False
    return False


def write_dynamic_imports(imports, output_file):
    """
    Write non-source (external) imports to the output file.

    Args:
        imports (list): List of AST import nodes.
        output_file (file-like): File object opened for writing.

    Example:
        with open("output.py", "w") as f:
            write_dynamic_imports(imports, f)
    """
    # Collect non-source imports and merge/deduplicate them
    non_source_imports = collect_non_source_imports(imports)
    print(non_source_imports)

    if non_source_imports:
        # Clean up the imports before writing
        cleaned_imports = clean_up_imports(non_source_imports)

        # Write cleaned imports at the top
        for imp in cleaned_imports:
            output_file.write(imp + "\n")


def clean_up_imports(non_source_imports):
    """
    Clean and format a set of non-source imports for output.
    - Deduplicates imports
    - Merges imports from the same module
    - Sorts alphabetically

    Args:
        non_source_imports (dict): Mapping of module -> set of names

    Returns:
        list of str: Cleaned import statements as strings.

    Example:
        lines = clean_up_imports({'os': {'*'}, 'collections': {'defaultdict', 'Counter'}})
    """
    clean_imports = []

    # Process and sort the imports
    for module, names in non_source_imports.items():
        if '*' in names:
            clean_imports.append(f"import {module}")
        else:
            sorted_names = sorted(names)  # Sort the names alphabetically
            clean_imports.append(f"from {module} import {', '.join(sorted_names)}")

    # Sort the import statements alphabetically
    clean_imports.sort()

    return clean_imports


def remove_unused_imports(file_path: str):
    """
    Removes unused imports and variables from a Python file using autoflake.

    Args:
        file_path (str): Path to the Python file to be cleaned.

    Raises:
        FileNotFoundError: If the given file path does not exist.
        RuntimeError: If autoflake fails to process the file.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"🚨🚩🚨 No such file: {file_path}")

    try:
        subprocess.run([
            "autoflake",
            "--in-place",
            "--remove-unused-variables",
            "--remove-all-unused-imports",
            "--expand-star-imports",
            str(path)
        ], check=True)
        print(f"Cleaned unused imports in: {file_path}")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to process file with autoflake: {e}")


def write_flattened_script(imports, defs, output_path, preload_paths=None, global_vars=None, hardcoded_statement=None):
    """
    Write a flattened script to the output file, including imports, global variables,
    and all required definitions in the proper order. Removes unused imports at the end.

    Args:
        imports (set): Set of AST import nodes used in the project.
        defs (dict): Mapping from name to (node, file_path) for all definitions.
        output_path (str or Path): Path to write the flattened output file.
        preload_paths (list[Path], optional): List of files whose defs should be written first.
        global_vars (list, optional): List of AST assignment nodes for globals.
        hardcoded_statement (str, optional): Additional code to insert at the top of the file.

    Example:
        write_flattened_script(imports, defs, "flattened.py", [Path("utils.py")])
    """
    preload_paths = preload_paths or []
    preload_paths = [Path(p).resolve() for p in preload_paths]

    # Group by file
    from collections import defaultdict
    file_to_defs = defaultdict(list)
    for name, (node, file_path) in defs.items():
        file_to_defs[file_path].append(node)

    with open(output_path, 'w') as out:
        # Write Top file comment
        out.write(ON_TOP_FILE_COMMENT.strip())
        out.write("\n")

        # Write dynamic imports at the top
        write_dynamic_imports(imports, out)
        out.write("\n")  # Separate dynamic imports and other code

        # Write the specific statements
        if hardcoded_statement:
            out.write(hardcoded_statement.strip() + "\n\n")

        # Write global variables at the top after imports
        if global_vars:
            # remove duplicates
            unique_globals = set([ast.unparse(var) for var in global_vars])
            for glob in unique_globals:
                out.write(glob)  # Write global variable assignment
                out.write("\n" * 1)

        # Write definitions from preload paths first, in list order
        print(f'🛣️PRELOADED PATH: {preload_paths}')
        for preload_path in preload_paths:
            preload_path = preload_path.resolve()
            for node in file_to_defs.get(preload_path, []):
                out.write("\n" * 2)  # Two newlines before each node
                out.write(ast.unparse(node))  # Write the node (class, function, etc.)
                out.write("\n" * 1)  # One newline after each node

        # Write remaining defs (not in preload list)
        written = set()
        for preload_path in preload_paths:
            written.update(file_to_defs.get(preload_path.resolve(), []))

        for file_path, nodes in file_to_defs.items():
            print(f'🏗️ {file_path} - {nodes}')
            if file_path.resolve() not in preload_paths and len(nodes) == 1:
                for node in nodes:
                    out.write("\n" * 2)  # Two newlines before each node
                    out.write(ast.unparse(node))  # Write the node (class, function, etc.)
                    out.write("\n" * 1)  # One newline after each node

    # Remove unused import and other variables
    remove_unused_imports(output_path)


def generate_main_prod_script():
    global ignore_imports

    # Default values for preload and ignoreImport
    default_preload = ['helpers/math_tools.py', 'utils.py']
    #default_preload = []
    default_ignore = []

    # Argument parser setup
    parser = argparse.ArgumentParser()

    # Adding argument for preload files (optional)
    parser.add_argument('--preload', nargs='*', help='Files to load first, in order', default=default_preload)

    # Adding argument for objects to ignore in imports (optional)
    parser.add_argument('--ignoreImport', nargs='*', help='Ignore import for given Objects', default=default_ignore)

    # Adding mandatory arguments for entry file and output path
    parser.add_argument('--entryFile', nargs='*', default="../sample_project/main.py",
                        help='Path to the entry file to process (e.g., workato_main_sync_data.py)')
    parser.add_argument('--outputPath', nargs='*', default="../sample_project/workato_prod_main.py",
                        help='Path to the output file for the flattened script')

    # Parsing the arguments
    args = parser.parse_args()

    # Set the global ignore imports list
    ignore_imports = args.ignoreImport

    # Preload paths
    preload_paths = [SRC_DIR / preload for preload in args.preload]

    # Entry file and output path
    entry_file = Path(args.entryFile).resolve()  # Resolve to an absolute path
    output_path = Path(args.outputPath).resolve()  # Resolve to an absolute path

    # Ensure entry_file exists
    if not entry_file.exists():
        print(f"🚨 Error: The entry file '{entry_file}' does not exist.")
        return

    # Ensure the directory for output_path exists
    if not output_path.parent.exists():
        print(f"🚨 Error: The directory for output path '{output_path.parent}' does not exist.")
        return

    # Collect dependencies and generate the flattened script
    imports, defs, global_vars = collect_dependencies(entry_file, preload_paths=preload_paths)
    write_flattened_script(
        imports, defs, output_path, preload_paths=preload_paths, global_vars=global_vars,
        hardcoded_statement=HARDCODED_STATEMENTS
    )

    # Inform the user that the script was generated
    print(f"[✅] Flattened script written to: {output_path}")


if __name__ == '__main__':
    generate_main_prod_script()
