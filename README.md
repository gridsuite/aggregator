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

Quick backend maven compile with changes in a few libs (example):
```
$ mvn compile -DskipTests -pl servers/study-server/ -am -Dpowsybl-ws-commons.version=1.6.0-SNAPSHOT
[INFO] ------------------------------------------------------------------------
[INFO] Reactor Build Order:
[INFO]
[INFO] powsybl ws commons                                                 [jar]
[INFO] Study Server                                                       [jar]
```
