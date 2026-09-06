extends RefCounted

const INVALID_ID: int = -1
const DEFAULT_TAG := &"none"

enum Kind {
	FIRST,      # a comment INSIDE the braces — folds wrong without care
	SECOND,
	THIRD = 7,
}
