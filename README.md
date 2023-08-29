# Gridsuite Aggregator

Inital clone
```
$ git clone --recurse-submodules --remote-submodules --jobs 8 https://github.com/gridsuite/aggregator
$ git submodule foreach --recursive 'git checkout main'
```

Update all
```
# --rebase or --merge as you wish
$ git submodule update --remote --recursive --rebase --jobs 8
```
