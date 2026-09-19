import re

with open("src/model/button.py", "r") as f:
    content = f.read()

# 1. Add method to ButtonCondition
content = content.replace("    color: bool = True", "    color: bool = True\n    method: str = \"exact\"")

# 2. Add method parsing in load_yaml
patch_load = """                    requires[roi_name] = ButtonCondition(
                        roi_name=roi_name,
                        template=t_val,
                        threshold=parse_threshold(cond.get("threshold"), default=btn_threshold),
                        color=bool(cond.get("color", True)),
                        method=cond.get("method", "exact"),
                    )"""
content = re.sub(r'                    requires\[roi_name\] = ButtonCondition\(\s*roi_name=roi_name,\s*template=t_val,\s*threshold=parse_threshold\(cond\.get\("threshold"\), default=btn_threshold\),\s*color=bool\(cond\.get\("color", True\)\),\s*\)', patch_load, content)

# 3. Add method to evaluate
patch_eval = """                    score, pos, tpl_size = matcher.match_detailed(
                        crop, tpl, color=condition.color, method=condition.method
                    )"""
content = re.sub(r'                    score, pos, tpl_size = matcher\.match_detailed\(\s*crop, tpl, color=condition\.color\s*\)', patch_eval, content)

with open("src/model/button.py", "w") as f:
    f.write(content)
