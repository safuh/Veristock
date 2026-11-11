import 'package:dio/dio.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/network/api_client.dart';
import 'features/auth/models/organization.dart';
import 'features/stocktaking/presentation/stocktaking_home_page.dart';

final apiClientProvider = Provider<ApiClient>((ref) => ApiClient());

class VeristockApp extends ConsumerStatefulWidget {
  const VeristockApp({super.key});

  @override
  ConsumerState<VeristockApp> createState() => _VeristockAppState();
}

class _VeristockAppState extends ConsumerState<VeristockApp> {
  bool _loading = true;
  String? _error;
  String? _identifier;
  List<Organization> _organizations = const [];
  Organization? _selectedOrganization;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _restoreSession());
  }

  Future<void> _restoreSession() async {
    try {
      final identity = await ref.read(apiClientProvider).restoreSession();
      _applyIdentity(identity);
    } catch (_) {
      // A missing or expired refresh token simply returns the user to sign-in.
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _applyIdentity(Map<String, dynamic> identity) {
    final organizations = (identity['organizations'] as List<dynamic>)
        .map((item) => Organization.fromJson(item as Map<String, dynamic>))
        .toList();
    setState(() {
      _identifier = identity['identifier'] as String;
      _organizations = organizations;
      _selectedOrganization =
          organizations.isEmpty ? null : organizations.first;
      _error = null;
    });
  }

  Future<void> _signIn(String identifier, String password) async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final identity = await ref.read(apiClientProvider).signIn(
            identifier: identifier,
            password: password,
          );
      _applyIdentity(identity);
    } on DioException catch (error) {
      setState(() => _error = _apiError(error));
    } catch (error) {
      setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _signOut() async {
    try {
      await ref.read(apiClientProvider).signOut();
    } finally {
      if (mounted) {
        setState(() {
          _identifier = null;
          _organizations = const [];
          _selectedOrganization = null;
        });
      }
    }
  }

  String _apiError(DioException error) {
    final body = error.response?.data;
    if (body is Map<String, dynamic> && body['detail'] is String) {
      return body['detail'] as String;
    }
    return error.message ?? 'Unable to connect to Veristock.';
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Veristock Field',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF315C45),
          brightness: Brightness.light,
        ),
        useMaterial3: true,
        scaffoldBackgroundColor: const Color(0xFFF5F7F4),
      ),
      home: _loading
          ? const _LoadingPage()
          : _identifier == null
              ? _LoginPage(error: _error, onSubmit: _signIn)
              : _selectedOrganization == null
                  ? _NoOrganizationPage(
                      identifier: _identifier!,
                      onSignOut: _signOut,
                    )
                  : StocktakingHomePage(
                      identifier: _identifier!,
                      organizations: _organizations,
                      selectedOrganization: _selectedOrganization!,
                      onOrganizationChanged: (organization) =>
                          setState(() => _selectedOrganization = organization),
                      onSignOut: _signOut,
                    ),
    );
  }
}

class _LoadingPage extends StatelessWidget {
  const _LoadingPage();

  @override
  Widget build(BuildContext context) => const Scaffold(
        body: Center(child: CircularProgressIndicator()),
      );
}

class _LoginPage extends StatefulWidget {
  const _LoginPage({required this.error, required this.onSubmit});

  final String? error;
  final Future<void> Function(String identifier, String password) onSubmit;

  @override
  State<_LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<_LoginPage> {
  final _formKey = GlobalKey<FormState>();
  final _identifier = TextEditingController();
  final _password = TextEditingController();
  bool _submitting = false;

  @override
  void dispose() {
    _identifier.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _submitting = true);
    await widget.onSubmit(_identifier.text.trim(), _password.text);
    if (mounted) setState(() => _submitting = false);
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        body: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 420),
                child: Form(
                  key: _formKey,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      const Icon(Icons.inventory_2_outlined, size: 52),
                      const SizedBox(height: 20),
                      Text(
                        'Veristock Field',
                        style: Theme.of(context).textTheme.headlineMedium,
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 8),
                      const Text(
                        'Sign in to your assigned stocktaking workspace.',
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 28),
                      TextFormField(
                        controller: _identifier,
                        keyboardType: TextInputType.emailAddress,
                        decoration: const InputDecoration(
                          labelText: 'Email or username',
                          border: OutlineInputBorder(),
                        ),
                        validator: (value) =>
                            value == null || value.trim().isEmpty
                                ? 'Enter your account identifier'
                                : null,
                      ),
                      const SizedBox(height: 14),
                      TextFormField(
                        controller: _password,
                        obscureText: true,
                        decoration: const InputDecoration(
                          labelText: 'Password',
                          border: OutlineInputBorder(),
                        ),
                        validator: (value) => value == null || value.isEmpty
                            ? 'Enter your password'
                            : null,
                        onFieldSubmitted: (_) => _submit(),
                      ),
                      if (widget.error != null) ...[
                        const SizedBox(height: 12),
                        Text(
                          widget.error!,
                          style: TextStyle(
                            color: Theme.of(context).colorScheme.error,
                          ),
                        ),
                      ],
                      const SizedBox(height: 20),
                      FilledButton(
                        onPressed: _submitting ? null : _submit,
                        child: Text(_submitting ? 'Signing in…' : 'Sign in'),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      );
}

class _NoOrganizationPage extends StatelessWidget {
  const _NoOrganizationPage({
    required this.identifier,
    required this.onSignOut,
  });

  final String identifier;
  final VoidCallback onSignOut;

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Veristock Field')),
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.domain_disabled_outlined, size: 48),
                const SizedBox(height: 12),
                const Text('No active organization assigned'),
                Text('Signed in as $identifier'),
                const SizedBox(height: 16),
                OutlinedButton(
                  onPressed: onSignOut,
                  child: const Text('Sign out'),
                ),
              ],
            ),
          ),
        ),
      );
}
