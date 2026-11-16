import 'package:flutter_test/flutter_test.dart';
import 'package:lia_manuscript/main.dart';
void main(){testWidgets('Pantalla inicial', (tester) async {await tester.pumpWidget(const LiaManuscriptApp());expect(find.text('Estudio de traducción literaria'),findsOneWidget);});}
