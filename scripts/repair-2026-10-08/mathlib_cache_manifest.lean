import Cache.Hashing

-- Run only against the frozen official sources. This exports their official
-- cache keys; it does not compile any theorem or change the upstream hash code.
def main : IO Unit := Cache.IO.CacheM.run do
  let memo ← Cache.Hashing.getHashMemo #[]
  for (path, value) in memo.hashMap.toArray do
    IO.println <| Lean.Json.compress <| .mkObj [
      ("module", .str path.toString),
      ("ltar", .str value.asLTar)]
