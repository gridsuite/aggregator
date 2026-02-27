# Gridsuite Aggregator

## Inital clone
```
$ git clone --recurse-submodules --remote-submodules --jobs 8 https://github.com/gridsuite/aggregator
$ git submodule foreach --recursive 'git checkout main'
```

## Update all
```
# --rebase or --merge as you wish
$ git submodule update --remote --recursive --rebase --jobs 8
```

## Review and merge a PR across all submodules

Replace `<branch>` with the PR branch name.

### 1. Checkout the branch in all submodules
```
$ git submodule foreach --recursive '
  git fetch origin &&
  git checkout <branch> 2>/dev/null || echo "branch not found"'
```

### 2. Review each diff interactively
```
$ git submodule foreach --recursive '
  bash -c "
    echo \"=== \$name ===\";
    gh pr diff <branch> || true;
    read -r -p \"Press Enter to continue...\"
  "
'
```

### 3. Approve all PRs
```
$ git submodule foreach --recursive 'gh pr review <branch> --approve || true'
```

### 4. Auto-merge all PRs
```
$ git submodule foreach --recursive 'gh pr merge <branch> --auto --squash || true'
```

## Java Compile
### Partial recompile
Setting a version property matching the current source code version of an
artifact causes it to be recompiled as part of the build. This is an
easy way to change code in libs and see consequences in dependent projects (e.g. servers). For example:
```
$ cd backend
$ mvn package -pl servers/study-server -am -Dpowsybl-ws-commons.version=1.6.0-SNAPSHOT
[INFO] ------------------------------------------------------------------------
[INFO] Reactor Build Order:
[INFO]
[INFO] powsybl ws commons                                                 [jar]
[INFO] Study Server                                                       [jar]
```

### Faster Multithreaded compile (useful for the long subsequent commands)

add `-T 2.0C` (optionally adjust the number of threads) to the mvn command line flags to build in parallel.
This has the downside of interleaving the output of all builds. An alternative is to use `mvnd` which displays
an interactive progress and dumps all the build logs at the end in the correct order and has `-T2.0C` on by default and starts faster.

### Full java recompile for one project and dependencies
A full java recompile for all dependent libs for one project can be done like this (adapt version numbers to match current versions in source poms)
```
$ cd backend
$ mvn package -pl servers/study-server -am \
  -Dpowsybl-ws-commons.version=1.6.0-SNAPSHOT \
  -Dpowsybl-ws-dependencies.version=2.4.0-SNAPSHOT \
  -Dpowsybl-core.version=6.0.0-SNAPSHOT \
  -Dgridsuite-dependencies.version=26-SNAPSHOT \
  -Dpowsybl-dependencies.version=2023.3.0-SNAPSHOT \
  -Dpowsybl-open-loadflow.version=1.3.0-SNAPSHOT \
  -Dpowsybl-diagram.version=4.0.0-SNAPSHOT \
  -Dpowsybl-dynawo.version=1.15.0-SNAPSHOT \
  -Dpowsybl-entsoe.version=2.6.0-SNAPSHOT \
  -Dpowsybl-case-datasource-client.version=1.3.0-SNAPSHOT \
  -Dpowsybl-network-store-client.version=1.4.0-SNAPSHOT \
  -Dpowsybl-open-reac.version=0.3.0-SNAPSHOT
[INFO] ------------------------------------------------------------------------
[INFO] Reactor Build Order:
[INFO]
[INFO] powsybl                                                            [pom]
[INFO] Commons test                                                       [jar]
[INFO] Commons                                                            [jar]
[INFO] powsybl ws commons                                                 [jar]
[INFO] Config Classic                                                     [jar]
[INFO] Config Test                                                        [jar]
[INFO] Triple store abstraction                                           [pom]
[INFO] Triple store abstraction API                                       [jar]
[INFO] RDF4J triple store implementation                                  [jar]
[INFO] CGMES                                                              [pom]
[INFO] CGMES network model                                                [jar]
[INFO] Computation API                                                    [jar]
[INFO] Tools                                                              [jar]
[INFO] Tools test                                                         [jar]
[INFO] Local computation                                                  [jar]
[INFO] Math                                                               [jar]
[INFO] IIDM                                                               [pom]
[INFO] IIDM network model                                                 [jar]
[INFO] IIDM common extensions                                             [jar]
[INFO] Load-flow                                                          [pom]
[INFO] Load-flow API                                                      [jar]
[INFO] IIDM testing networks                                              [jar]
[INFO] IIDM TCK                                                           [jar]
[INFO] IIDM network model implementation                                  [jar]
[INFO] IIDM XML converter                                                 [jar]
[INFO] Network modifications                                              [jar]
[INFO] Contingency                                                        [pom]
[INFO] Contingency API                                                    [jar]
[INFO] Security Analysis                                                  [pom]
[INFO] Security analysis API                                              [jar]
[INFO] AMPL converter implementation                                      [jar]
[INFO] AMPL model executor                                                [jar]
[INFO] CGMES extensions                                                   [jar]
[INFO] CGMES network model test                                           [jar]
[INFO] CGMES conformity                                                   [jar]
[INFO] Load-flow validation                                               [jar]
[INFO] Loadflow Results Completion                                        [jar]
[INFO] CGMES conversion                                                   [jar]
[INFO] Time series                                                        [pom]
[INFO] Time series API                                                    [jar]
[INFO] ENTSO-E utilities                                                  [jar]
[INFO] IEEE CDF                                                           [pom]
[INFO] IEEE CDF model                                                     [jar]
[INFO] IEEE CDF converter                                                 [jar]
[INFO] Sensitivity analysis API                                           [jar]
[INFO] Short-circuit API                                                  [jar]
[INFO] Network store client parent                                        [pom]
[INFO] Network store model                                                [jar]
[INFO] Network store IIDM impl                                            [jar]
[INFO] Network store client                                               [jar]
[INFO] powsybl open loadflow                                              [jar]
[INFO] PowSyBl Optimizer                                                  [pom]
[INFO] OpenReac                                                           [jar]
[INFO] Study Server                                                       [jar]
```

TODO: can the version finding be automated?
TODO: should we use .mvn/maven.config to record versions and maintain the list ?

### Rebuild only all docker images

```
# in maven4, aggregators automatically represent their reactor children
$ cd backend/servers
$ mvn install -Dpowsybl.docker.install
```

```
# maven3, semi manual hack project list with ls, to be tweaked to have the correct project list
$ cd backend/servers
$ mvn install -Dpowsybl.docker.install \
  -pl $(echo $(ls -d */) | sed -e 's/ /,/g')
```

### Full java recompile for all docker images
A full java recompile and docker image generation for all projects
```
$ cd backend
$ mvn install -Dpowsybl.docker.install \
  -Dpowsybl-ws-commons.version=1.6.0-SNAPSHOT \
  -Dpowsybl-ws-dependencies.version=2.4.0-SNAPSHOT \
  -Dpowsybl-core.version=6.0.0-SNAPSHOT \
  -Dgridsuite-dependencies.version=26-SNAPSHOT \
  -Dpowsybl-dependencies.version=2023.3.0-SNAPSHOT \
  -Dpowsybl-open-loadflow.version=1.3.0-SNAPSHOT \
  -Dpowsybl-diagram.version=4.0.0-SNAPSHOT \
  -Dpowsybl-dynawo.version=1.15.0-SNAPSHOT \
  -Dpowsybl-entsoe.version=2.6.0-SNAPSHOT \
  -Dpowsybl-case-datasource-client.version=1.3.0-SNAPSHOT \
  -Dpowsybl-network-store-client.version=1.4.0-SNAPSHOT \
  -Dpowsybl-open-reac.version=0.3.0-SNAPSHOT
```
TODO: can enforce that there is no source code that is ignored in this step ?

### Full java recompile with modified build system (powsybl-parent)
TODO. can this be done without modifying files ?

To use a modified parent, modify the relativePath and the parent version in the tested projects:
```
     <parent>
         <groupId>com.powsybl</groupId>
         <artifactId>powsybl-parent-ws</artifactId>
-        <version>12</version>
-        <relativePath/>
+        <version>14-SNAPSHOT</version>
+        <relativePath>../../build/powsybl-parent/powsybl-parent/powsybl-parent-ws</relativePath>
     </parent>
```

```
$ mvn package -pl servers/study-server/ -am
[INFO] Scanning for projects...
[INFO] ------------------------------------------------------------------------
[INFO] Reactor Build Order:
[INFO]
[INFO] Powsybl                                                            [pom]
[INFO] Powsybl Build Tools                                                [jar]
[INFO] Powsybl Parent                                                     [pom]
[INFO] Powsybl Parent WS                                                  [pom]
[INFO] Study Server                                                       [jar]
```
