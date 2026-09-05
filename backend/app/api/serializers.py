def row_to_dict(row):
    d = {}
    for col in row.__table__.columns:
        val = getattr(row, col.name)
        d[col.name] = val
    return d
