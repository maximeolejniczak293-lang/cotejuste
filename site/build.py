"""Assemble le site : injecte data.json dans le gabarit HTML."""
import os
HERE = os.path.dirname(os.path.abspath(__file__))
data = open(os.path.join(HERE, "..", "out", "data.json"), encoding="utf-8").read().replace("</", "<\\/")
tpl = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
assert "/*__DATA__*/" in tpl
html = tpl.replace("/*__DATA__*/", data)
open(os.path.join(HERE, "index.html"), "w", encoding="utf-8").write(html)
print("index.html :", len(html) // 1024, "Ko")
