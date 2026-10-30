from urllib.parse import unquote


class PlayerNameConverter:
    """
    URL segment for a player name, which can contain any character, including "/".

    WSGI servers decode %XX escapes before Django routes a request, so a slash encoded as a
    plain "%2F" would be indistinguishable from a path separator. to_url escapes "%" and "/"
    itself, and reverse() then percent-encodes that result again, so the escapes survive the
    server's decoding pass (e.g. "a/b" is linked as "a%252Fb") and to_python undoes them.
    """

    regex = "[^/]+"

    def to_python(self, value):
        return unquote(value)

    def to_url(self, value):
        return value.replace("%", "%25").replace("/", "%2F")
