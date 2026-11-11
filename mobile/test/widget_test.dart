import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter/material.dart';

import 'package:veristock_mobile/app.dart';

void main() {
  testWidgets('renders the Veristock field application', (tester) async {
    await tester.pumpWidget(
      const ProviderScope(child: VeristockApp()),
    );
    await tester.pump();
    expect(find.byType(MaterialApp), findsOneWidget);
  });
}
