# Bug Notes

Initial decode failed on special tokens.

The bug was fixed by preserving special token byte sequences during decode instead of sending them through the normal byte merge path.
