"""Original GitPython assertion API over a separately executed native query."""
import git
from types import SimpleNamespace
BASE='d6987af002b122fef54bc0be402062c76488a4d9'
def install(result):
 assert result['protocol']=='sanitize-original-git-diff-v1'
 assert result['privateCandidateCodeExecution'] is False
 paths=result['paths'];assert isinstance(paths,list) and len(paths)<=10000
 assert all(isinstance(p,str) and len(p.encode())<=8192 for p in paths)
 def repo(path):
  assert str(path)=='/app/dclm'
  def commit(value):
   assert value==BASE
   def diff(other):
    assert other is None
    return [SimpleNamespace(b_path=p) for p in paths]
   return SimpleNamespace(diff=diff)
  return SimpleNamespace(commit=commit)
 git.Repo=repo
