"""解析 "key=value;key=value" 形式的记录。"""


def parse_line(line):
    record = {}
    key = ""
    value = ""
    in_value = False
    for ch in line:
        if ch == "=" and not in_value:
            in_value = True
        elif ch == ";":
            record[key.strip()] = value.strip()
            key, value, in_value = "", "", False
        elif in_value:
            value = value + ch
        else:
            key = key + ch
    if key.strip():
        record[key.strip()] = value.strip()
    return record


def parse(text):
    return [parse_line(line) for line in text.splitlines() if line.strip()]
