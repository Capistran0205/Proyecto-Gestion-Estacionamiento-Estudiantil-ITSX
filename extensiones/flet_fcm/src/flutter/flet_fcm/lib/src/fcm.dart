import 'dart:async';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flet/flet.dart';
import 'package:flutter/widgets.dart';

class FcmService extends FletService {
  FcmService({required super.control});

  final List<StreamSubscription<dynamic>> _suscripciones = [];
  bool _escuchando = false;

  @override
  void init() {
    super.init();
    debugPrint("Fcm(${control.id}).init");
    control.addInvokeMethodListener(_invokeMethod);
  }

  Future<dynamic> _invokeMethod(String name, dynamic args) async {
    switch (name) {
      case "inicializar":
        await _inicializar(args);
        return null;
      case "pedir_permiso":
        final ajustes = await FirebaseMessaging.instance.requestPermission();
        return ajustes.authorizationStatus == AuthorizationStatus.authorized ||
            ajustes.authorizationStatus == AuthorizationStatus.provisional;
      case "obtener_token":
        return await FirebaseMessaging.instance.getToken();
      case "borrar_token":
        await FirebaseMessaging.instance.deleteToken();
        return null;
      case "mensaje_inicial":
        final mensaje = await FirebaseMessaging.instance.getInitialMessage();
        return mensaje == null ? null : _mapa(mensaje);
      default:
        throw Exception("Unknown Fcm method: $name");
    }
  }

  Future<void> _inicializar(dynamic args) async {
    if (Firebase.apps.isEmpty) {
      await Firebase.initializeApp(
        options: FirebaseOptions(
          apiKey: args["api_key"],
          appId: args["app_id"],
          messagingSenderId: args["sender_id"],
          projectId: args["project_id"],
        ),
      );
    }
    if (_escuchando) return;
    _escuchando = true;
    _suscripciones.addAll([
      FirebaseMessaging.instance.onTokenRefresh.listen((token) {
        control.triggerEvent("token_refresh", {"token": token});
      }),
      FirebaseMessaging.onMessage.listen((mensaje) {
        control.triggerEvent("message", _mapa(mensaje));
      }),
      FirebaseMessaging.onMessageOpenedApp.listen((mensaje) {
        control.triggerEvent("message_opened", _mapa(mensaje));
      }),
    ]);
  }

  Map<String, dynamic> _mapa(RemoteMessage mensaje) => {
        "titulo": mensaje.notification?.title,
        "cuerpo": mensaje.notification?.body,
        "datos": mensaje.data,
      };

  @override
  void dispose() {
    debugPrint("Fcm(${control.id}).dispose()");
    for (final suscripcion in _suscripciones) {
      suscripcion.cancel();
    }
    _suscripciones.clear();
    control.removeInvokeMethodListener(_invokeMethod);
    super.dispose();
  }
}
