import AppKit
import Combine
import SwiftUI

/// The composition root: the only place that knows the window layer, the views
/// and the run model at once. Wiring and the two menus; no other logic.
///
/// An `@main` type rather than `main.swift`, because top-level code is not
/// main-actor isolated in Swift 5 language mode.
@main
enum SystemOneApp {

    @MainActor
    static func main() {
        let model = RunModel()
        let appDelegate = AppDelegate { PanelRootView(model: model) }
        var cancellables = Set<AnyCancellable>()

        // Model → window.
        model.requestOpen = { [weak appDelegate] in appDelegate?.openPanel() }
        model.requestClose = { [weak appDelegate] in appDelegate?.closePanel() }
        model.onContentHeightChange = { [weak appDelegate] height in
            appDelegate?.updateContentHeight(height)
        }

        // Window → model.
        appDelegate.onPanelOpen = { model.panelDidOpen() }
        appDelegate.onPanelClose = { model.panelWillClose() }
        // A click while the run has the screen locks the panel, which shows the
        // run's status strip, with its Stop, in place of the panel.
        appDelegate.takeClick = {
            guard model.isRunning else { return false }
            model.isPinned = true
            return true
        }
        appDelegate.contextMenu = { appMenu(model) }
        // Quitting mid-run stops the run, as Ctrl-C would, rather than orphaning it.
        appDelegate.onTerminate = { model.stop() }

        // The lock keeps the panel open, and so does a question waiting on the
        // user: an outside click must not decline it.
        model.$phase
            .map { phase -> Bool in
                if case .asking = phase { return true }
                return false
            }
            .combineLatest(model.$isPinned)
            .map { $0 || $1 }
            .removeDuplicates()
            .sink { [weak appDelegate] pinned in
                appDelegate?.panelController.isPinned = pinned
            }
            .store(in: &cancellables)

        // Locked, the panel stays on screen through the run as a status strip.
        model.$phase
            .combineLatest(model.$isPinned)
            .map { $0 == .running && $1 }
            .removeDuplicates()
            .sink { [weak appDelegate] on in
                appDelegate?.showRunStrip(on)
            }
            .store(in: &cancellables)

        // The abort key stops the run from any app while one is live.
        let abortHotKey = AbortHotKey()
        model.$phase
            .map { $0 != .idle && $0 != .finished }
            .removeDuplicates()
            .sink { live in
                if live {
                    abortHotKey.register(AbortKey.current) { model.stop() }
                } else {
                    abortHotKey.unregister()
                }
            }
            .store(in: &cancellables)

        // The status item shows that a run has the screen, and its step.
        model.$phase
            .combineLatest(model.$step)
            .sink { [weak appDelegate] state in
                appDelegate?.showRun(running: state.0 == .running, step: state.1)
            }
            .store(in: &cancellables)

        let application = NSApplication.shared
        application.delegate = appDelegate
        // Never returns, so everything above lives as long as the process.
        withExtendedLifetime((appDelegate, model, cancellables, abortHotKey)) {
            application.run()
        }
    }

    /// A right click: the lock, the last run's folder, settings, and Quit.
    @MainActor
    private static func appMenu(_ model: RunModel) -> NSMenu {
        let menu = NSMenu()
        menu.autoenablesItems = false
        menu.addItem(ClosureMenuItem("Keep Panel Open", state: model.isPinned ? .on : .off) {
            model.isPinned.toggle()
        })
        let folder = ClosureMenuItem("Open Last Run Folder") { model.openRunFolder() }
        folder.isEnabled = model.runFolder != nil
        menu.addItem(folder)
        if model.isRunning {
            menu.addItem(ClosureMenuItem("Stop") { model.stop() })
        }
        menu.addItem(.separator())
        let settings = ClosureMenuItem("Settings…") {
            model.openSettings()
            model.requestOpen?()
        }
        settings.isEnabled = !model.isRunning && !model.isAsking
        menu.addItem(settings)
        menu.addItem(.separator())
        menu.addItem(ClosureMenuItem("Quit System One") { NSApp.terminate(nil) })
        return menu
    }
}
