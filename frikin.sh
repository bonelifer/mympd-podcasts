git push -u origin fix/default-port-and-now-playing-title
gh pr create --fill
gh pr checks --watch
gh pr merge --squash --delete-branch
