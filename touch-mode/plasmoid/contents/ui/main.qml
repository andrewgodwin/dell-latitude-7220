import QtQuick
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.notification
import org.kde.plasma.components as PlasmaComponents
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasma5support as P5Support
import org.kde.plasma.plasmoid

PlasmoidItem {
    id: root

    readonly property var modes: [
        { name: "finger", label: i18n("Finger"), icon: "input-touchscreen-symbolic" },
        { name: "glove", label: i18n("Glove"), icon: "hand" },
        { name: "water", label: i18n("Water"), icon: "raindrop" },
    ]

    // "" until the first successful query
    property string mode: ""
    property string error: ""
    property bool setPending: false

    readonly property var currentMode: modes.find(m => m.name === mode) ?? null
    readonly property string helper: Qt.resolvedUrl("../code/touchmode_helper.py").toString().replace(/^file:\/\//, "")

    function refresh() {
        if (!setPending) {
            executable.run(["get"]);
        }
    }

    function setMode(name) {
        setPending = true;
        executable.run(["set", name]);
    }

    Plasmoid.status: PlasmaCore.Types.ActiveStatus
    Plasmoid.icon: error ? "dialog-warning" : (currentMode?.icon ?? "input-touchscreen-symbolic")
    toolTipMainText: i18n("Touch Mode")
    toolTipSubText: error ? error : (currentMode ? currentMode.label : i18n("Unknown"))

    Plasmoid.contextualActions: modes.map(m => modeActionComponent.createObject(root, { modeData: m }))

    Component {
        id: modeActionComponent

        PlasmaCore.Action {
            property var modeData

            text: modeData.label
            icon.name: modeData.icon
            checkable: true
            checked: root.mode === modeData.name
            onTriggered: {
                // Triggering toggles `checked`; restore the binding so the
                // menu reflects the device's actual state.
                checked = Qt.binding(() => root.mode === modeData.name);
                root.setMode(modeData.name);
            }
        }
    }

    onExpandedChanged: {
        if (expanded) {
            refresh();
        }
    }

    Component.onCompleted: refresh()

    P5Support.DataSource {
        id: executable

        function run(args) {
            const quoted = [root.helper, ...args].map(a => "'" + a.replace(/'/g, "'\\''") + "'");
            connectSource("python3 " + quoted.join(" "));
        }

        engine: "executable"
        connectedSources: []

        onNewData: (sourceName, data) => {
            disconnectSource(sourceName);
            const isSet = sourceName.includes("'set'");
            if (isSet) {
                root.setPending = false;
            } else if (root.setPending) {
                // A poll raced with a set; the set's result is authoritative.
                return;
            }

            let result;
            try {
                result = JSON.parse(data["stdout"]);
            } catch (e) {
                result = { ok: false, error: (data["stderr"] || i18n("Helper produced no output")).trim() };
            }

            if (result.ok) {
                root.mode = result.mode;
                root.error = "";
            } else {
                root.error = result.error;
                if (isSet) {
                    failNotification.text = result.error;
                    failNotification.sendEvent();
                }
            }
        }
    }

    Notification {
        id: failNotification

        componentName: "plasma_workspace"
        eventId: "notification"
        title: i18n("Could not change touch mode")
        iconName: "dialog-warning"
    }

    // Background poll, in case the mode was changed by something else.
    Timer {
        interval: 60 * 1000
        running: true
        repeat: true
        onTriggered: root.refresh()
    }

    // Detect resume from suspend: timers don't tick while asleep, so a
    // large gap between ticks means we've just woken up.
    Timer {
        property double lastTick: Date.now()

        interval: 5 * 1000
        running: true
        repeat: true
        onTriggered: {
            const now = Date.now();
            if (now - lastTick > interval * 4) {
                root.refresh();
            }
            lastTick = now;
        }
    }

    fullRepresentation: ColumnLayout {
        Layout.preferredWidth: Kirigami.Units.gridUnit * 14
        Layout.preferredHeight: implicitHeight
        Layout.minimumWidth: Kirigami.Units.gridUnit * 12
        spacing: Kirigami.Units.smallSpacing

        PlasmaComponents.Label {
            Layout.fillWidth: true
            visible: root.error !== ""
            text: root.error
            wrapMode: Text.Wrap
            color: Kirigami.Theme.negativeTextColor
        }

        Repeater {
            model: root.modes

            delegate: PlasmaComponents.Button {
                required property var modelData

                Layout.fillWidth: true
                Layout.preferredHeight: Kirigami.Units.gridUnit * 3
                text: modelData.label
                icon.name: modelData.icon
                icon.width: Kirigami.Units.iconSizes.medium
                icon.height: Kirigami.Units.iconSizes.medium
                // Not checkable, so clicks don't flip it before the device confirms.
                checked: root.mode === modelData.name
                enabled: !root.setPending
                onClicked: root.setMode(modelData.name)
            }
        }

        Item {
            Layout.fillHeight: true
        }
    }
}
