# SystemOne.app

The menu bar front end for `clicker`, built from
[Menu-Bar-Chat](https://github.com/kydno/Menu-Bar-Chat)'s non-activating panel. What it does, how
to build it, and the permissions it needs are in [docs/menu-bar.md](../docs/menu-bar.md).

```
Package.swift     SwiftPM, macOS 26; no Xcode project
Info.plist        copied into the bundle; build.sh adds this checkout's path
Scripts/          build.sh, run.sh, and the login item
Sources/SystemOne/
  App/            the status item, the non-activating panel and where it sits, and Bootstrap,
                  the composition root that wires them to the model
  Core/           Constants (every number and string), Motion, AgentProcess (one
                  `clicker --events` run), AgentEvent (its events), Project (where clicker is)
  State/          RunModel, the only interface between the views and the run
  Views/          the input bar, the run box, the glass
```

As in Menu-Bar-Chat, `Views/` talks only to `RunModel`, `App/` knows neither, and
`App/Bootstrap.swift` is the one place that knows all three.
