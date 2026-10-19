"""Validated theme roles shared by stylesheets and custom-painted widgets."""
DEFAULT = {"panel": "#252930", "control": "#363d46", "accent": "#c4ee70", "text": "#dce1d6",
           "display": "#10160f", "secondary": "#e8b768", "border": "#6b737e", "muted": "#959fa9"}
ACTIVE = dict(DEFAULT)
SOFT_LIGHT = {"panel": "#f6f3ee", "control": "#faf8f4", "accent": "#a86846", "text": "#2d3038",
              "display": "#eeebe5", "secondary": "#8a5c3c", "border": "#d2cec6", "muted": "#676d78"}


def color(role):
    return ACTIVE[role]
