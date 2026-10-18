"""Validated theme roles shared by stylesheets and custom-painted widgets."""
DEFAULT = {"panel": "#252930", "control": "#363d46", "accent": "#c4ee70", "text": "#dce1d6",
           "display": "#10160f", "secondary": "#e8b768", "border": "#6b737e", "muted": "#959fa9"}
ACTIVE = dict(DEFAULT)


def color(role):
    return ACTIVE[role]
