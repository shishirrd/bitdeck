"""Pure page-range validation, shared by UI and worker."""

def page_indices(expression, count):
    """One-based inclusive ranges; order and duplicates are intentional."""
    if not isinstance(expression, str) or len(expression) > 4096:
        raise ValueError("Enter page numbers such as 1-3,5,8-6.")
    if not expression.strip():
        return list(range(count))
    result = []
    try:
        for part in expression.split(","):
            ends = part.strip().split("-")
            if len(ends) == 1:
                result.append(int(ends[0]) - 1)
            elif len(ends) == 2:
                a, b = map(int, ends)
                if not 1 <= a <= count or not 1 <= b <= count:
                    raise ValueError()
                step = 1 if b >= a else -1
                result.extend(range(a - 1, b - 1 + step, step))
            else:
                raise ValueError()
            if len(result) > 200:
                raise ValueError()
        if not result or any(index < 0 or index >= count for index in result):
            raise ValueError()
    except ValueError as error:
        raise ValueError("Page range is invalid or outside this PDF (maximum 200 selected pages).") from error
    return result

