# gRPC services and method matrix

This table lists every RPC method in the Quilt API proto definitions, along with its request and response types and what (if anything) the library does with it.

## HomeDatastoreService

Defined in `quilt_hds.proto`. Package: `core.protos.home_datastore`.

| Method | Request | Response | Library wrapper |
| --- | --- | --- | --- |
| `GetHomeDatastoreSystem` | `GetHomeDatastoreSystemRequest` | `HomeDatastoreSystem` | `HomeDatastoreService.get_system()` → `SystemSnapshot` |
| `UpdateSpace` | `UpdateSpaceRequest` | `Space` | `HomeDatastoreService.update_space()` and `update_space_settings()` → `Space` |
| `UpdateIndoorUnit` | `UpdateIndoorUnitRequest` | `IndoorUnit` | `HomeDatastoreService.update_indoor_unit()` and `update_indoor_unit_settings()` → `IndoorUnit` |
| `UpdateComfortSetting` | `UpdateComfortSettingRequest` | `ComfortSetting` | `HomeDatastoreService.update_comfort_setting()` → `ComfortSetting` |
| `CreateScheduleDay` | `CreateScheduleDayRequest` | `ScheduleDay` | `HomeDatastoreService.create_schedule_day()` → `ScheduleDay` |
| `UpdateScheduleDay` | `UpdateScheduleDayRequest` | `ScheduleDay` | `HomeDatastoreService.update_schedule_day()` → `ScheduleDay` |
| `DeleteScheduleDay` | `DeleteScheduleDayRequest` | `Empty` | `HomeDatastoreService.delete_schedule_day()` |
| `CreateScheduleWeek` | `CreateScheduleWeekRequest` | `ScheduleWeek` | `HomeDatastoreService.create_schedule_week()` → `ScheduleWeek` |
| `UpdateScheduleWeek` | `UpdateScheduleWeekRequest` | `ScheduleWeek` | `HomeDatastoreService.update_schedule_week()` → `ScheduleWeek` |
| `DeleteScheduleWeek` | `DeleteScheduleWeekRequest` | `Empty` | `HomeDatastoreService.delete_schedule_week()` |
| `UpdateLocation` | `UpdateLocationRequest` | `Location` | `HomeDatastoreService.update_location_schedule_execution()`; pauses/resumes schedules |

Beyond the wrapped methods above, the server implements generic CRUD for every Home Datastore
entity: `Get<Entity>`, `Create<Entity>`, `Update<Entity>`, `Delete<Entity>` and `List<Entities>` for
spaces, indoor/outdoor units, controllers, smart modules, remote sensors, comfort settings, schedule
days/weeks, locations, software-update infos, air handlers, ducted zones and memberships,
automations, demand-response events and the four hardware types (105 methods; the Quilt app itself
calls 32). All are declared in `quilt_hds.proto`, each tagged with how it was verified.

| Pattern | Request | Response |
| --- | --- | --- |
| `Get<E>` | `{ object_id = 1; [field_mask = 2] }` (per-entity `include_*` mask where defined) | `<E>` |
| `Create<E>` / `Update<E>` | `{ <E> <e> = 1 }` (Update takes a partial diff) | `<E>` |
| `Delete<E>` | `{ object_id = 1 }` | `Empty` |
| `List<Es>` | `{ filter = 2 }`, e.g. `header.system_id="<uuid>"`; returns every accessible object when empty | `{ repeated <E> = 1 }` |

## CommandService

Defined in `quilt_hds.proto`. Package: `core.protos.home_datastore`. New in the Quilt app versionCode 255; cloud stub only (no local endpoint).

| Method | Request | Response | Library wrapper |
| --- | --- | --- | --- |
| `RequestFastUpdates` | `RequestFastUpdatesRequest` | `RequestFastUpdatesResponse` (empty) | `CommandService.request_fast_updates()` → `None`; also `QuiltClient.request_fast_updates()` |

## SystemInformationService

Defined in `quilt_services.proto`. Package: `core.protos.app`.

| Method | Request | Response | Library wrapper |
| --- | --- | --- | --- |
| `ListSystems` | `ListSystemInformationRequest` | `ListSystemInformationResponse` | `SystemInformationService.list_systems()` → `list[SystemInfo]` |
| `GetEnergyMetrics` | `GetEnergyMetricsRequest` | `GetEnergyMetricsResponse` | `SystemInformationService.get_energy_metrics()` → `list[SpaceEnergyMetrics]` |
| `SetAddress` | `SetAddressRequest` | `SetAddressResponse` (empty) | Not wrapped |
| `GetSystemDataSharing` / `SetSystemDataSharing` | `*SystemDataSharingRequest` | `SystemDataSharing` | Not wrapped |
| `ListSystemCertifiedPartners` | `ListSystemCertifiedPartnersRequest` | `ListSystemCertifiedPartnersResponse` | Not wrapped |
| `GetPartnerDesignationPlan` / `SetSystemPartner` | `*Request` | `GetPartnerDesignationPlanResponse` / `SetSystemPartnerResponse` | Not wrapped |

## UserService

Defined in `quilt_services.proto`. Package: `core.protos.app`.

| Method | Request | Response | Library wrapper |
| --- | --- | --- | --- |
| `GetLoggedInUser` | `GetLoggedInUserRequest` | `GetLoggedInUserResponse` | `UserService.get_current_user()` → `User` |
| `UpdateLoggedInUser` | `UpdateLoggedInUserRequest` | `UpdateLoggedInUserResponse` | `UserService.update_current_user()` → `User` |
| `GetUserAttributes` | `GetUserAttributesRequest` | `GetUserAttributesResponse` (wraps `UserAttributes`) | `UserService.get_user_attributes()` → `UserAttributes` |
| `PatchUserAttributes` | `PatchUserAttributesRequest` | `UserAttributes` | `UserService.patch_user_attributes()` → `UserAttributes` |

## NotifierService

Defined in `quilt_notifier.proto`. Package: `core.protos.notifier`.

| Method | Request | Response | Stream type | Library wrapper |
| --- | --- | --- | --- | --- |
| `Subscribe` | `stream SubscribeRequest` | `stream SubscribeResponse` | Bidirectional | `NotifierStream`; full lifecycle management |

`Publish` also exists server-side; its shape is unknown and it is not declared.

## InvitationService

Defined in `quilt_services.proto`. Not currently wrapped by the library.

| Method | Request | Response |
| --- | --- | --- |
| `ListPendingInvitationsForLoggedInUser` | `ListPendingInvitationsRequest` | `ListPendingInvitationsResponse` |
| `CreateInvitation` | `CreateInvitationRequest` | `CreateInvitationResponse` |
| `AcceptInvitation` | `AcceptInvitationRequest` | `AcceptInvitationResponse` |
| `RejectInvitation` | `RejectInvitationRequest` | `RejectInvitationResponse` |
| `CancelInvitation` | `CancelInvitationRequest` | `CancelInvitationResponse` |
| `SendNotificationForInvitation` | `SendNotificationForInvitationRequest` | `SendNotificationForInvitationResponse` |

## PartnerService

Defined in `quilt_services.proto`. Not wrapped by this library.

| Method | Request | Response |
| --- | --- | --- |
| `InviteSystemOwner` | `InviteSystemOwnerRequest` | `InviteSystemOwnerResponse` |
| `GetLoggedInUserPartnerDetails` | `GetLoggedInUserPartnerDetailsRequest` | `GetLoggedInUserPartnerDetailsResponse` |
| `JoinPartnerOrganization` | `JoinPartnerOrganizationRequest` | `PartnerDetails` |
| `LeavePartnerOrganization` | `LeavePartnerOrganizationRequest` | `Empty` |

## SystemUserService

Defined in `quilt_services.proto`. Not currently wrapped by the library.

| Method | Request | Response |
| --- | --- | --- |
| `ListSystemUsers` | `ListSystemUsersRequest` | `ListSystemUsersResponse` |
| `GetRoleOfLoggedInSystemUser` | `GetRoleOfLoggedInSystemUserRequest` | `GetRoleOfLoggedInSystemUserResponse` |
| `RemoveSystemUser` | `RemoveSystemUserRequest` | `RemoveSystemUserResponse` |
| `RemoveLoggedInSystemUser` | `RemoveLoggedInSystemUserRequest` | `RemoveLoggedInSystemUserResponse` |
| `ChangeRoleOfSystemUser` | `ChangeRoleOfSystemUserRequest` | `ChangeRoleOfSystemUserResponse` |

## HomeActionService

Defined in `quilt_actions.proto`. Package: `core.protos.actions`. Not currently wrapped by the library.

| Method | Request | Response |
| --- | --- | --- |
| `SubmitAction` | `SubmitActionRequest` | `SubmitActionResponse` |

## DeviceConfigurationService

Defined in `quilt_device_config.proto` (payloads in `quilt_device_pairing.proto`, which are also
used over BLE). Package: `core.protos.common`. Plaintext gRPC on port 50051 of a device in setup
mode. Not currently wrapped by the library.

| Method | Request | Response |
| --- | --- | --- |
| `GetSupportedDeviceConfigVersion` | `GetSupportedDeviceConfigVersionRequest` | `GetSupportedDeviceConfigVersionResponse` |
| `GetWifiScanResults` | `GetWifiScanResultsRequest` | `WifiScanList` |
| `SendDeviceConfigRequest` | `DeviceConfigurationRequest` | `DeviceConfigurationResult` |

## SystemService

Defined in `quilt_system.proto`. Package: `core.protos.system`. Not currently wrapped by the library.

| Method | Request | Response |
| --- | --- | --- |
| `GetSystem` | `GetSystemRequest` | `System` |
| `CreateSystem` / `UpdateSystem` | `CreateSystemRequest` / `UpdateSystemRequest` | `System` |
| `DeleteSystem` | `DeleteSystemRequest` | `Empty` |
| `ListSystems` | `ListSystemsRequest` | `ListSystemsResponse` |

## MobileAppService

Defined in `quilt_services.proto`. Not currently wrapped by the library.

| Method | Request | Response |
| --- | --- | --- |
| `AuthorizeNewDevice` | `AuthorizeNewDeviceRequest` | `AuthorizeNewDeviceResponse` |
| `CreateAndConfigureSystem` | `CreateAndConfigureSystemRequest` | `CreateAndConfigureSystemResponse` |
| `CreateAndConfigureSpace` | `CreateAndConfigureSpaceRequest` | `CreateAndConfigureSpaceResponse` |
| `CreateAndConfigureDuctedZone` | `CreateAndConfigureDuctedZoneRequest` | `CreateAndConfigureDuctedZoneResponse` |

## DiagnosticService, UserTaskService, UserFeedbackService

Defined in `quilt_services.proto`. Not wrapped: installer diagnostics (`StartDiagnosticRun`,
`CancelDiagnosticRun`), the onboarding task list (`ListUserTasks`, `CaptureUserAction`) and in-app
feedback (`SubmitUserFeedback`).
