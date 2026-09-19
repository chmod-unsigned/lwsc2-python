import re

with open("src/model/state.py", "r") as f:
    content = f.read()

# 1. Add method to StateCondition
content = content.replace("    color: bool = True", "    color: bool = True\n    method: str = \"exact\"")

# 2. Add method parsing in load_yaml
patch_load = """                    requires[roi_name] = StateCondition(
                        roi_name=roi_name,
                        template=t_val,
                        threshold=parse_threshold(cond.get("threshold"), default=state_threshold),
                        color=bool(cond.get("color", True)),
                        method=cond.get("method", "exact"),
                    )"""
content = re.sub(r'                    requires\[roi_name\] = StateCondition\(\s*roi_name=roi_name,\s*template=t_val,\s*threshold=parse_threshold\(cond\.get\("threshold"\), default=state_threshold\),\s*color=bool\(cond\.get\("color", True\)\),\s*\)', patch_load, content)

# 3. Add method to evaluate
patch_eval = """                    score = matcher.compute_similarity(
                        crop, tpl, color=condition.color, method=condition.method
                    )"""
content = re.sub(r'                    score = matcher\.compute_similarity\(\s*crop, tpl, color=condition\.color\s*\)', patch_eval, content)

with open("src/model/state.py", "w") as f:
    f.write(content)
