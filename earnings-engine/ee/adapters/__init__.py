"""Vendor adapters for WW-EARNINGS. One file per vendor, same shape as
factor-engine/fac/adapters and data-router/router/adapters: a class that
either makes a real, documented HTTP call or, in every sandbox this repo
has been built in so far, raises a named, honest "not configured / no
network here" error — never a silent fake value.
"""
