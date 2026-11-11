import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:veristock_mobile/app.dart';
import 'package:veristock_mobile/core/network/api_client.dart';

class _TestApiClient extends ApiClient {
  @override
  Future<Map<String, dynamic>> restoreSession() async {
    throw StateError('No test session');
  }
}

void main() {
  testWidgets('shows sign-in form when no mobile session exists', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          apiClientProvider.overrideWithValue(_TestApiClient()),
        ],
        child: const VeristockApp(),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byType(MaterialApp), findsOneWidget);
    expect(find.text('Veristock Field'), findsOneWidget);
    expect(find.text('Sign in'), findsOneWidget);
  });
}
