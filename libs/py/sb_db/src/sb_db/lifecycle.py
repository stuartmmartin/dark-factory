"""A unit of work is single-use: once committed or rolled back its buffers refuse new work."""

FINISHED = "unit of work already finished"
