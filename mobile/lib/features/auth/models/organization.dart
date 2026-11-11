class Organization {
  const Organization({
    required this.id,
    required this.kind,
    required this.legalName,
    this.tradingName,
    required this.timezone,
  });

  final String id;
  final String kind;
  final String legalName;
  final String? tradingName;
  final String timezone;

  String get displayName => tradingName ?? legalName;

  factory Organization.fromJson(Map<String, dynamic> json) => Organization(
        id: json['id'] as String,
        kind: json['kind'] as String,
        legalName: json['legal_name'] as String,
        tradingName: json['trading_name'] as String?,
        timezone: json['timezone'] as String,
      );
}
