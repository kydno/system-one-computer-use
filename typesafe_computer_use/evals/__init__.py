"""An offline eval kit built from the run folders a real machine has already written.

Nothing here drives a computer. `cases` freezes each saved step into a case, `digest` says where runs
failed, `decisions` asks the decision model about the cases again, and `budget` stops any command that
spends money outside a batch the user approved. See docs/improvement-loop.md.
"""
