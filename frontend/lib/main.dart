import 'package:flutter/material.dart';
import 'core/theme/lia_theme.dart';
import 'screens/home_screen.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const LiaManuscriptApp());
}

class LiaManuscriptApp extends StatelessWidget {
  const LiaManuscriptApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'LIA Manuscript',
    debugShowCheckedModeBanner: false,
    theme: LiaTheme.dark,
    home: const HomeScreen(),
  );
}
