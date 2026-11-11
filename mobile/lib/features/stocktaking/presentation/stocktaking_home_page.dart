import 'package:dio/dio.dart';
import 'package:material_ui/material_ui.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../../../core/network/api_client.dart';
import '../../auth/models/organization.dart';

class StocktakingHomePage extends StatefulWidget {
  const StocktakingHomePage({
    super.key,
    required this.identifier,
    required this.apiClient,
    required this.organizations,
    required this.selectedOrganization,
    required this.onOrganizationChanged,
    required this.onSignOut,
  });

  final String identifier;
  final ApiClient apiClient;
  final List<Organization> organizations;
  final Organization selectedOrganization;
  final ValueChanged<Organization> onOrganizationChanged;
  final VoidCallback onSignOut;

  @override
  State<StocktakingHomePage> createState() => _StocktakingHomePageState();
}

class _StocktakingHomePageState extends State<StocktakingHomePage> {
  bool _loading = true;
  String? _error;
  List<Map<String, dynamic>> _stocktakes = const [];

  @override
  void initState() {
    super.initState();
    _loadStocktakes();
  }

  @override
  void didUpdateWidget(covariant StocktakingHomePage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.selectedOrganization.id !=
        widget.selectedOrganization.id) {
      _loadStocktakes();
    }
  }

  Future<void> _loadStocktakes() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final records = await widget.apiClient
          .listStocktakes(widget.selectedOrganization.id);
      if (!mounted) return;
      setState(() {
        _stocktakes = records
            .where((record) => record['status'] == 'open')
            .toList();
      });
    } on DioException catch (error) {
      if (mounted) setState(() => _error = _message(error));
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  String _message(DioException error) {
    final body = error.response?.data;
    if (body is Map<String, dynamic> && body['detail'] is String) {
      return body['detail'] as String;
    }
    return error.message ?? 'Unable to load assigned stocktakes.';
  }

  Future<void> _openStocktake(Map<String, dynamic> stocktake) async {
    final completed = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => StocktakeCountPage(
          apiClient: widget.apiClient,
          organizationId: widget.selectedOrganization.id,
          stocktake: stocktake,
        ),
      ),
    );
    if (completed == true) {
      await _loadStocktakes();
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          title: const Text('Veristock Field'),
          actions: [
            IconButton(
              tooltip: 'Refresh stocktakes',
              onPressed: _loadStocktakes,
              icon: const Icon(Icons.refresh),
            ),
            IconButton(
              tooltip: 'Sign out',
              onPressed: widget.onSignOut,
              icon: const Icon(Icons.logout),
            ),
          ],
        ),
        body: RefreshIndicator(
          onRefresh: _loadStocktakes,
          child: ListView(
            padding: const EdgeInsets.all(20),
            children: [
              Text('FIELD OPERATIONS',
                  style: Theme.of(context).textTheme.labelSmall),
              const SizedBox(height: 6),
              Text('Ready for stocktaking',
                  style: Theme.of(context).textTheme.headlineSmall),
              const SizedBox(height: 18),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('ACTIVE ORGANIZATION'),
                      const SizedBox(height: 8),
                      DropdownButtonFormField<Organization>(
                        initialValue: widget.selectedOrganization,
                        isExpanded: true,
                        items: widget.organizations
                            .map((organization) => DropdownMenuItem(
                                  value: organization,
                                  child: Text(organization.displayName,
                                      overflow: TextOverflow.ellipsis),
                                ))
                            .toList(),
                        onChanged: (organization) {
                          if (organization != null) {
                            widget.onOrganizationChanged(organization);
                          }
                        },
                      ),
                      const SizedBox(height: 8),
                      Text('Signed in as ${widget.identifier}',
                          style: Theme.of(context).textTheme.bodySmall),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 20),
              Row(
                children: [
                  Expanded(
                    child: Text('Open stocktakes',
                        style: Theme.of(context).textTheme.titleLarge),
                  ),
                  Text('${_stocktakes.length}'),
                ],
              ),
              if (_error != null) ...[
                const SizedBox(height: 12),
                Text(_error!,
                    style: TextStyle(color: Theme.of(context).colorScheme.error)),
              ],
              if (_loading)
                const Padding(
                  padding: EdgeInsets.all(28),
                  child: Center(child: CircularProgressIndicator()),
                )
              else if (_stocktakes.isEmpty)
                const Card(
                  child: Padding(
                    padding: EdgeInsets.all(22),
                    child: Text(
                      'No open stocktakes are available in this organization. '
                      'Ask an administrator to create a stocktake.',
                      textAlign: TextAlign.center,
                    ),
                  ),
                )
              else
                ..._stocktakes.map(
                  (stocktake) => Card(
                    child: ListTile(
                      leading: const CircleAvatar(
                        child: Icon(Icons.inventory_2_outlined),
                      ),
                      title: Text(stocktake['reference'] as String),
                      subtitle: Text(
                        '${stocktake['item_count']} items · '
                        'Created ${(stocktake['created_at'] as String).split('T').first}',
                      ),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () => _openStocktake(stocktake),
                    ),
                  ),
                ),
              const SizedBox(height: 20),
              Card(
                child: ListTile(
                  leading: const Icon(Icons.cloud_sync_outlined),
                  title: const Text('Online count capture'),
                  subtitle: const Text(
                    'Counts are submitted directly to Veristock. Offline '
                    'queueing will be enabled after encrypted sync storage '
                    'and conflict handling are implemented.',
                  ),
                ),
              ),
            ],
          ),
        ),
      );
}

class StocktakeCountPage extends StatefulWidget {
  const StocktakeCountPage({
    super.key,
    required this.apiClient,
    required this.organizationId,
    required this.stocktake,
  });

  final ApiClient apiClient;
  final String organizationId;
  final Map<String, dynamic> stocktake;

  @override
  State<StocktakeCountPage> createState() => _StocktakeCountPageState();
}

class _StocktakeCountPageState extends State<StocktakeCountPage> {
  bool _loading = true;
  bool _busy = false;
  String? _error;
  List<Map<String, dynamic>> _scope = const [];
  final Map<String, TextEditingController> _quantities = {};
  final Set<String> _saved = {};
  String? _matchedItemId;

  @override
  void initState() {
    super.initState();
    _loadScope();
  }

  @override
  void dispose() {
    for (final controller in _quantities.values) {
      controller.dispose();
    }
    super.dispose();
  }

  Future<void> _loadScope() async {
    try {
      final scope = await widget.apiClient.stocktakeScope(
        widget.organizationId,
        widget.stocktake['id'] as String,
      );
      for (final item in scope) {
        _quantities[item['item_id'] as String] = TextEditingController();
      }
      if (mounted) setState(() => _scope = scope);
    } on DioException catch (error) {
      if (mounted) setState(() => _error = _message(error));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  String _message(DioException error) {
    final body = error.response?.data;
    if (body is Map<String, dynamic> && body['detail'] is String) {
      return body['detail'] as String;
    }
    return error.message ?? 'Unable to load count items.';
  }

  Future<void> _scanItem() async {
    final barcode = await Navigator.of(context).push<String>(
      MaterialPageRoute<String>(
        builder: (_) => const _BarcodeScannerPage(),
      ),
    );
    if (!mounted || barcode == null) return;
    Map<String, dynamic>? match;
    for (final item in _scope) {
      if (item['barcode'] == barcode) {
        match = item;
        break;
      }
    }
    if (match == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Barcode is not in this stocktake scope.')),
      );
      return;
    }
    final itemId = match['item_id'] as String;
    setState(() => _matchedItemId = itemId);
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('Matched ${match?['name']}. Enter its physical quantity.')),
    );
  }

  Future<void> _saveCount(Map<String, dynamic> item) async {
    final itemId = item['item_id'] as String;
    final quantity = _quantities[itemId]!.text.trim();
    if (quantity.isEmpty || double.tryParse(quantity) == null ||
        double.parse(quantity) < 0) {
      setState(() => _error = 'Enter a valid quantity. Zero is allowed.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.apiClient.recordCount(
        organizationId: widget.organizationId,
        stocktakeId: widget.stocktake['id'] as String,
        itemId: itemId,
        quantity: quantity,
        unitCode: item['unit_code'] as String,
      );
      if (mounted) setState(() => _saved.add(itemId));
    } on DioException catch (error) {
      if (mounted) setState(() => _error = _message(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.apiClient.submitStocktake(
        organizationId: widget.organizationId,
        stocktakeId: widget.stocktake['id'] as String,
      );
      if (mounted) Navigator.of(context).pop(true);
    } on DioException catch (error) {
      if (mounted) setState(() => _error = _message(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          title: Text(widget.stocktake['reference'] as String),
          actions: [
            IconButton(
              tooltip: 'Scan barcode',
              onPressed: _loading ? null : _scanItem,
              icon: const Icon(Icons.qr_code_scanner),
            ),
          ],
        ),
        body: _loading
            ? const Center(child: CircularProgressIndicator())
            : ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  Card(
                    child: Padding(
                      padding: const EdgeInsets.all(14),
                      child: Text(
                        'Blind count · ${_saved.length} of ${_scope.length} items saved. '
                        'Expected quantities are not shown.',
                      ),
                    ),
                  ),
                  if (_error != null)
                    Padding(
                      padding: const EdgeInsets.all(8),
                      child: Text(_error!,
                          style: TextStyle(
                              color: Theme.of(context).colorScheme.error)),
                    ),
                  ..._scope.map((item) {
                    final itemId = item['item_id'] as String;
                    final saved = _saved.contains(itemId);
                    return Card(
                      child: Padding(
                        padding: const EdgeInsets.all(14),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(item['name'] as String,
                                style: Theme.of(context).textTheme.titleMedium),
                            if (_matchedItemId == itemId)
                              const Text('Barcode matched', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600)),
                            Text(
                              '${item['sku'] ?? item['barcode'] ?? ''} · '
                              '${item['unit_code']}',
                            ),
                            const SizedBox(height: 10),
                            Row(
                              children: [
                                Expanded(
                                  child: TextField(
                                    controller: _quantities[itemId],
                                    enabled: !saved && !_busy,
                                    keyboardType:
                                        const TextInputType.numberWithOptions(
                                      decimal: true,
                                    ),
                                    decoration: const InputDecoration(
                                      labelText: 'Physical quantity',
                                      border: OutlineInputBorder(),
                                    ),
                                  ),
                                ),
                                const SizedBox(width: 10),
                                FilledButton(
                                  onPressed: saved || _busy
                                      ? null
                                      : () => _saveCount(item),
                                  child: Text(saved ? 'Saved' : 'Save'),
                                ),
                              ],
                            ),
                          ],
                        ),
                      ),
                    );
                  }),
                  const SizedBox(height: 10),
                  FilledButton.icon(
                    onPressed: _busy ||
                            _scope.isEmpty ||
                            _saved.length != _scope.length
                        ? null
                        : _submit,
                    icon: const Icon(Icons.check_circle_outline),
                    label: const Text('Submit count round'),
                  ),
                ],
              ),
      );
}

class _BarcodeScannerPage extends StatefulWidget {
  const _BarcodeScannerPage();

  @override
  State<_BarcodeScannerPage> createState() => _BarcodeScannerPageState();
}

class _BarcodeScannerPageState extends State<_BarcodeScannerPage> {
  bool _handled = false;

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Barcode scanner')),
        body: MobileScanner(
          onDetect: (capture) {
            if (_handled || capture.barcodes.isEmpty) return;
            final value = capture.barcodes.first.rawValue;
            if (value == null || value.isEmpty) return;
            _handled = true;
            Navigator.of(context).pop(value);
          },
        ),
      );
}
