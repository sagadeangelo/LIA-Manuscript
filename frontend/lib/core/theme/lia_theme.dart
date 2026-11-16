import 'package:flutter/material.dart';

class LiaTheme {
  static const background = Color(0xFF0B1220);
  static const surface = Color(0xFF131E30);
  static const elevated = Color(0xFF1B2940);
  static const cyan = Color(0xFF22D3EE);
  static const violet = Color(0xFFA78BFA);
  static const text = Color(0xFFE8F0FA);
  static const muted = Color(0xFF9AABC3);

  static ThemeData get dark => ThemeData(
    useMaterial3: true,
    brightness: Brightness.dark,
    scaffoldBackgroundColor: background,
    colorScheme: const ColorScheme.dark(
      primary: cyan, secondary: violet, surface: surface,
      onSurface: text,
    ),
    appBarTheme: const AppBarTheme(backgroundColor: background, foregroundColor: text),
    cardTheme: CardThemeData(color: surface, shape: RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(14),
      side: const BorderSide(color: Color(0xFF273953)),
    )),
    inputDecorationTheme: InputDecorationTheme(
      filled: true, fillColor: elevated,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
      enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: Color(0xFF33445E))),
    ),
  );
}
