import 'package:flet/flet.dart';

import 'fcm.dart';

class Extension extends FletExtension {
  @override
  FletService? createService(Control control) {
    switch (control.type) {
      case "Fcm":
        return FcmService(control: control);
      default:
        return null;
    }
  }
}
