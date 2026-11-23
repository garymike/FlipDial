"""Extraction (milestone 2): read cropped card images with a local model.

Results are validated against a strict schema.

Card text is untrusted input. The model gets no tools and no network access, and anything
outside the schema is dropped.
"""
