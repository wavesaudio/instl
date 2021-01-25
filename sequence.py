# todo:
# args bug

import logging
import sys
import sqlite3
import json

log = logging.getLogger(__name__)

from pybatch import *


def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d


waves_central_log_content = None
db = sqlite3.connect('local.db')
db.row_factory = dict_factory
cur = db.cursor()
now = config_vars["__NOW__"]


def init_db():
    create_table_sql = """
        CREATE TABLE actions_sequence 
        (
            _id INTEGER ,
            products TEXT ,
            repo_rev JSON,
            os_version TEXT,
            action TEXT,
            central_version TEXT,
            environment TEXT,
            date DATE,
            succeeded BOOLEAN DEFAULT TRUE,
            PRIMARY KEY (_id, action)
        );
    """

    try:
        cur.execute(create_table_sql)
    except Exception as exp:
        pass
    return db


def translate_macros_to_keys(key):
    macro_translate_dict = {"REPO_REV": 'repo_rev', "__MAIN_INSTALL_IIDS__": 'products', "__MAIN_COMMAND__": 'action',
                            "__NOW__": 'date', "CENTRAL_VERSION": 'central_version',
                            "__CURRENT_OS_DESCRIPTION__": "os_version", "S3_BUCKET_NAME": "environment"}
    return macro_translate_dict[key]


def scan_file_for_fields(config_input: dict, fields):
    """
    scans a file and extracts fields from the file content/file name
    """
    global now
    ret_val = dict()
    separator = ', '
    for key in fields:
        if key in config_input:
            if key == '__NOW__' and now == config_input[key]:
                ret_val[translate_macros_to_keys(key)] = None
            else:
                ret_val[translate_macros_to_keys(key)] = separator.join(config_input[key])

    return ret_val


def get_files_by_type(dst_dir, type):
    path_expr = dst_dir + "/*." + type
    files = glob.glob(path_expr)
    return files


def extract_id_from_file(filename):
    filename = Path(filename).name
    args = filename.split(sep="_")
    last_part = args.pop()
    id = last_part.split(sep=".")
    return id[0]


def get_file_type(filename: str):
    if ".yaml" in filename:
        return "yaml"
    elif ".py" in filename:
        if "timings" in filename:
            return "run"
        else:
            return "prep"


def assign_id_type_file(files_list, res_dict):
    for file in files_list:
        if "require" in file:
            continue
        id = extract_id_from_file(file)
        type = get_file_type(file)
        res_dict[id][type] = file


def get_relevant_files_by_id_by_type(dst_dir):
    res = defaultdict(dict)
    py_files = get_files_by_type(dst_dir, "py")
    assign_id_type_file(py_files, res)
    return res


def insert_to_db(keys, values):
    table_name = 'actions_sequence'
    columns = ', '.join(keys)
    placeholders = ', '.join('?' * len(values))
    sql = r"INSERT INTO " + table_name + r" ({}) VALUES ({}) ".format(columns, placeholders)
    try:
        cur.execute(sql, values)
        db.commit()
    except Exception as exp:
        pass


def get_config_vars_path(path):
    relevant_lines = []
    with open(path, encoding='utf-8') as fo:
        for line in fo:
            if "config_vars" in line:
                relevant_lines.append(line.strip())
    conts = "\n".join(relevant_lines)
    exec(conts)


def import_module_by_path(path):
    name = os.path.splitext(os.path.basename(path))[0]
    if sys.version_info[:2] <= (3, 4):
        from importlib.machinery import SourceFileLoader
        return SourceFileLoader(name, path).load_module()
    else:
        import importlib.util
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod


def read_file(filename):
    with config_vars.push_scope_context() as context:

        script_folder = Path(filename)
        build_python_script = script_folder.resolve()

        try:
            get_config_vars_path(build_python_script)
        except Exception as exp:
            pass
        keys = ["REPO_REV", "__MAIN_INSTALL_IIDS__", "__MAIN_COMMAND__", "__NOW__", "CENTRAL_VERSION",
                "__CURRENT_OS_DESCRIPTION__", "S3_BUCKET_NAME"]
        ret_dict = scan_file_for_fields(config_vars, keys)
        prods = find_products_in_waves_central_log(logs_folder + "/Waves-Central.log", script_folder.name)
        ret_dict['action'] = adjust_actions(ret_dict['action'])
        if ret_dict['date'] is None:
            modTimesinceEpoc = os.path.getmtime(filename)
            ret_dict['date'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(modTimesinceEpoc))
        if len(prods) > 0:
            ret_dict["products"] = ",".join(prods)
        else:
            # in this case it means that there is probably another relevant entry with the relevant products
            if ret_dict['action'] == "synccopy":
                ret_dict['action'] = "filter"  # TODO: should unite the repo_rev as json
        return ret_dict


def unite_same_id_lines(id):
    global table_name, cur
    sql = f"""
        SELECT repo_rev from {table_name} where _id={id}
    """
    cur.execute(sql)


def lib_scan(logs_path):
    global id_to_repos
    files_to_scan = get_relevant_files_by_id_by_type(logs_path)
    for timestamp, file_dict in files_to_scan.items():
        for key, filename in file_dict.items():
            if key == 'run':
                continue
            data = read_file(filename)

            if "-" in timestamp:
                version, ts = timestamp.split("-")
                if 'repo_rev' in data:
                    data['repo_rev'] = json.dumps({version: data['repo_rev']})
                data['_id'] = int(ts)
            else:
                data['_id'] = int(timestamp)

            if "run" in file_dict.keys():
                data['succeeded'] = True
            else:
                data['succeeded'] = False
            if data['action'] != "filter":
                insert_to_db(list(data.keys()), list(data.values()))
            else:
                id_to_repos[data['_id']] = json.loads(data['repo_rev'])


def index_containing_substring(the_list, substring):
    for i, s in enumerate(the_list):
        if substring in s:
            return i
    return -1


def find_products_in_waves_central_log(logsfolderpath, filename):
    filename = filename.replace(".py", ".abort")
    global waves_central_log_content
    if not waves_central_log_content:
        with open(logsfolderpath, encoding='utf-8') as fo:
            waves_central_log_content = fo.readlines()
    products = []
    start_from = index_containing_substring(waves_central_log_content, filename)
    if start_from >= 0:
        relevant_content = waves_central_log_content[start_from + 1::]
        products_starting_line = index_containing_substring(relevant_content, 'Products:')
        clean_content = relevant_content[products_starting_line + 1:products_starting_line + 200]
        for i, line in enumerate(clean_content):
            if "[info]" not in line:
                products.append(line.strip("\t").strip("\n"))
            else:
                break
    return products


def adjust_actions(action_name):
    action_dict = {"exec": "cofix", "doit": "permission_fixer"}
    if action_name in action_dict:
        return action_dict[action_name]
    else:
        return action_name


def get_param(where, param):
    global cur, db
    sql = f"""
        SELECT {param} from actions_sequence where {where} order by date 
    """
    cur.execute(sql)
    db.commit()
    rows = cur.fetchall()
    return rows


def get_sorted_actions_lits(where='', to_json=True):
    global cur, db
    sql = f"""
        SELECT * from actions_sequence {where} order by date 
    """
    cur.execute(sql)
    db.commit()
    retVal = cur.fetchall()
    arrange_sorted_list(retVal)
    if to_json:
        retVal = json.dumps(retVal)
    print (retVal)

def arrange_sorted_list(rows):
    global id_to_repos
    for idx, row in enumerate(rows):
        cur_id = row['_id']
        if row['action'] == 'synccopy' and cur_id in id_to_repos:
            tmp = json.loads(row['repo_rev'])
            tmp.update(id_to_repos[cur_id])
            row['repo_rev'] = tmp


db = init_db()
cur = db.cursor()
id_to_repos = {}
logs_folder = "/Users/orenc/Downloads/Users 4/dougieb/Library/Application Support/Waves Audio/Waves Central/Logs"
# if len(sys.argv) > 5:
#     logs_folder = sys.argv[5]

lib_scan(logs_folder + "/install")
lib_scan(logs_folder + "/uninstall")
lib_scan(logs_folder + "/permissionFixer")
lib_scan(logs_folder + "/Cofix_Logs")
get_sorted_actions_lits()
db.close()
