import os

import yara
import re

from typing import overload, Union, List

RULES_DIR = "rules"
SOURCE_FILE_EXTENSION = ".yar"
COMPILED_FILE_EXTENSION = ".bin"
CALLBACK_DICTS: list = []


def is_number(s: str) -> bool:
    """
    Checks is a string value is numeric.

    :param s:
    :return:
    """
    try:
        int(s)
        return True
    except ValueError:
        return False


def sanitize_rulename(rule_name: str) -> str:
    """
    Identifiers must follow the same lexical conventions of the C programming language,
    they can contain any alphanumeric character and the underscore character, but the
    first character can not be a digit. Rule identifiers are case sensitive and cannot
    exceed 128 characters.

    :param rule_name:
    :return:
    """
    # If the first character is a digit, prepend an underscore as
    # the first character can not be a digit.
    if is_number(rule_name[0]):
        rule_name = '_' + rule_name

    # Replace all non-word characters (everything except numbers and letters) with underscore.
    s = re.sub(r"[^\w\s+]", '_', rule_name)

    return s


def extract_yara_strings_dict(yara_artifacts: dict) -> dict:
    """
    Takes a yara artifacts dict (varname: {artifact, id, type} and returns a dict with only varname: {artifact}.
    :param yara_artifacts:
    :return: dict
    """
    return {k: yara_artifacts[k]["artifact"] for k in yara_artifacts}


def get_referenced_strings(cond_stmt: str, yara_strings: dict) -> dict:
    """
    In Yara it is a SyntaxError to have unreferenced strings/vars,
    so these need to be rinsed out before rule compilation.

    :param cond_stmt: str
    :param yara_strings: {}
    :return: Returns dict of strings that are referenced in the conditional statement.
    """
    # Find all occurrences of words starting with $ (i.e. variable names)
    r = re.compile(r'\$[\w]*\b')
    possible_matches = r.findall(cond_stmt)

    # Get rid of mismatches by making a list of items that only matches the actual strings/vars list.
    confirmed_items = {}
    for assumed in possible_matches:
        if assumed in yara_strings.keys():
            confirmed_items[assumed] = yara_strings[assumed]

    return confirmed_items


def generate_source_string(src: dict) -> str:
    """
    Generates a yara rule on string form.

    example format:
        rule RuleIdentifier
        {
            meta:
                description = ""

            strings:
                $artifact1 = ""

            condition:
                $artifact1
        }

    :param src: dict on the form of: {tags: [""], rule: "", meta: {}, strings: {}, condition: ""}
    :return:
    """
    identifier_line = "rule {}".format(src["rule"])
    meta = ""
    strings = ""
    condition = "    condition:" \
                "\n        {}".format(src["condition"])

    # Append tags to rule line, if provided.
    if "tags" in src:
        if len(src["tags"]) > 0:
            identifier_line = identifier_line + (": " + " ".join(src["tags"]))

    # Add the meta info block, if provided.
    if "meta" in src:
        if bool(src["meta"]):
            meta = "    meta:"
            for k, v in src["meta"].items():
                meta = meta + "\n        {} = \"{}\"".format(k, v)

    # Add the strings (read: variables) block, id provided.
    if "strings" in src:
        if bool(src["strings"]):
            strings = "    strings:"
            for k, v in get_referenced_strings(src["condition"], src["strings"]).items():
                strings = strings + "\n        {} = \"{}\"".format(k, v)

    # Compile the entire rule block string.
    rule_string =           \
        identifier_line     \
        + '\n' + '{'        \
        + '\n' + meta       \
        + '\n'              \
        + '\n' + strings    \
        + '\n'              \
        + '\n' + condition  \
        + '\n' + '}'

    return rule_string


def save_compiled(rules: yara.Rules, filename: str, file_ext=COMPILED_FILE_EXTENSION, rules_dir=RULES_DIR):
    """
    Saves compiled (binary) YARA rules to file.

    :param rules:
    :param filename:
    :param file_ext:
    :param rules_dir:
    :return:
    """
    # If destination directory does not exist, create it.
    if not os.path.isdir(rules_dir):
        os.mkdir(rules_dir)

    filepath = os.path.join(rules_dir, filename + file_ext)

    if isinstance(rules, yara.Rules):
        # Save compiled YARA rule to binary file using the Yara class' builtin.
        rules.save(filepath)
    else:
        raise ValueError("save_compiled: rules must be 'yara.Rules' object.")


def save_source(rules: str, filename: str, file_ext=SOURCE_FILE_EXTENSION, rules_dir=RULES_DIR):
    """
    Saves source (plaintext) YARA rules to file.

    :param rules:
    :param filename:
    :param file_ext:
    :param rules_dir:
    :return:
    """
    # If destination directory does not exist, create it.
    if not os.path.isdir(rules_dir):
        os.mkdir(rules_dir)

    filepath = os.path.join(rules_dir, filename + file_ext)

    if isinstance(rules, str):
        # Save YARA source rule to plaintext file using regular Python standard file I/O.
        with open(filepath, 'w') as f:
            f.write(rules)
    else:
        raise ValueError("save_source: rules must be 'str'.")


def load_file(filename: str, rules_dir=RULES_DIR):
    rules = None

    # If destination directory does not exist, return.
    if os.path.isdir(rules_dir):
        # Load rules from file.
        rules = yara.load(filepath=os.path.join(rules_dir, filename))

    return rules


def match_to_dict(match: yara.Match, condition: str = None, matches: bool = None) -> dict:
    """
    Copies yara.Match attributes and misc over to a more malleable dict.

    :param match:
    :param condition:
    :param matches:
    :return:
    """
    strings_tuples: List[tuple] = match.strings
    strings_dict: dict = {}

    for some_int, var, value in strings_tuples:
        strings_dict[var] = value

    return {"matches": matches, "rule": match.rule, "namespace": match.namespace, "tags": match.tags,
            "meta": match.meta, "strings": strings_dict, "condition": condition}


def compiled_rules_to_sources_str_callback(d: dict):
    """
    Callback function for when invoking yara.match method.
    The provided function will be called for every rule, no matter if matching or not.

    Function should expect a single parameter of dictionary type, and should return CALLBACK_CONTINUE
    to proceed to the next rule or CALLBACK_ABORT to stop applying rules to your data.
    :param d: Likely a dict.
    :return:
    """
    global CALLBACK_DICTS

    print("CALLBACK:")
    for key, value in d.items():
        print("\t{}: {}".format(key, value))
    CALLBACK_DICTS.append(d)

    # Continue/Step
    yara.CALLBACK_CONTINUE


@overload
def compiled_rules_to_source_string(rules: yara.Rules, condition: str) -> str:
    pass


@overload
def compiled_rules_to_source_string(rules: str, condition: str) -> str:
    pass


def compiled_rules_to_source_string(rules: Union[yara.Rules, str], condition: str) -> str:
    """
    Converts a compiled yara rule (binary) to a list of source strings (.yar format).

    :param rules:       yara.Rules object or path to a compiled yara rules .bin
    :param condition:   Required parameter as the condition seemingly is not part of the compiled YARA rule.
    :return:            List of source strings
    """
    global CALLBACK_DICTS

    if isinstance(rules, yara.Rules):
        complied_rules = rules
    elif isinstance(rules, str):
        complied_rules = load_file(filename=rules + COMPILED_FILE_EXTENSION)
    else:
        raise ValueError("rules must be 'yara.Rules' object or 'str' filepath to a compiled yara rules .bin")

    # The match method returns a list of instances of the class Match.
    # Instances of this class have the same attributes as the dictionary passed to the callback function.
    matches: yara.Match = complied_rules.match(filepath=os.path.join(RULES_DIR, rules + SOURCE_FILE_EXTENSION),
                                               callback=compiled_rules_to_sources_str_callback)

    # Copy Matches attributes and misc over to a more malleable dict.
    match = match_to_dict(matches[0], condition=condition, matches=CALLBACK_DICTS[0]["matches"])

    # Reset the global callback data list.
    CALLBACK_DICTS = []

    print("match:")
    for key, value in match.items():
        print("\t{}: {}".format(key, value))

    print("compiled_rules_to_source_strings matches: {}".format(match["matches"]))  # FIXME: Debug

    return generate_source_string(match)


def compile_from_source(yara_sources_dict: dict, error_on_warning=True, **kwargs) -> str:
    """
    Generates a yara rule based on a given dict on the form of:
     {rule: "", tags: [""], meta: {}, artifacts: [artifact: "", id: "", type: ""], condition: ""}.

    :param error_on_warning: If true warnings are treated as errors, raising an exception.
    :param yara_sources_dict:
    :return:
    """
    rule_name: str = sanitize_rulename(yara_sources_dict["rule"])
    source: str = generate_source_string({"tags": yara_sources_dict["tags"],
                                          "rule": rule_name,
                                          "meta": {k: yara_sources_dict["meta"][k] for k in yara_sources_dict["meta"]},
                                          "strings": extract_yara_strings_dict(yara_sources_dict["artifacts"]),
                                          "condition": yara_sources_dict["condition"]
                                          })

    print("source: \n{}".format(source))    # FIXME: DEBUG

    # Save source rule to text file.
    save_source(rules=source, filename=rule_name)

    try:
        compiled_yara_rules: yara.Rules = yara.compile(source=source,
                                                       error_on_warning=error_on_warning,
                                                       **kwargs)

        # Save compiled rule to binary file.  #FIXME: Change to verification/testing later.
        save_compiled(rules=compiled_yara_rules, filename=rule_name)

        retv = compiled_rules_to_source_string(rule_name, condition=yara_sources_dict["condition"])

        return retv

        # return compiled_yara_rules
    except (yara.SyntaxError, yara.Error) as yara_exc:
        print("generate_yara_rule_from_json Exception: {}".format(yara_exc))
        print("generate_yara_rule_from_json incoming dict: {}".format(yara_sources_dict))
        raise yara_exc
    except Exception as exc:
        print("generate_yara_rule_from_json UNEXPECTED Exception: {}".format(exc))
        print("generate_yara_rule_from_json incoming dict: {}".format(yara_sources_dict))
        raise exc
