// AppShots - Suggested Swift modifications for Potodoro
// Add these to your ContentView or App struct to support launch argument navigation
// Wrap in #if DEBUG to keep out of production builds

// Add to Potodoro/Potodoro/PotodoroApp.swift:

import SwiftUI
import SwiftData
import StoreKit // For AppStore.sync() if needed
import ActivityKit // For cleanupOldActivities
import UserNotifications // For notification permissions check

@main
struct PotodoroApp: App {
    @AppStorage("isOnboardingComplete") private var isOnboardingComplete = false
    @State private var showLaunchScreen = true
    @State private var initialTab: Int? = nil // New state for initial tab
    
    // MARK: - AppShots Debug Flags (AppStorage bridge for @State in child views)
    @AppStorage("debug_showPaywall") private var debugShowPaywall: Bool = false
    @AppStorage("debug_showStrainSelection") private var debugShowStrainSelection: Bool = false
    @AppStorage("debug_showBank") private var debugShowBank: Bool = false
    @AppStorage("debug_showTagCreationSheet") private var debugShowTagCreationSheet: Bool = false // For TagCreationSheet from StrainSelection
    @AppStorage("debug_showResetAlert") private var debugShowResetAlert: Bool = false
    @AppStorage("debug_showAboutAlert") private var debugShowAboutAlert: Bool = false
    @AppStorage("debug_showTagManagement") private var debugShowTagManagement: Bool = false // For Manage Tags from Settings
    @AppStorage("debug_showWitheredPlant") private var debugShowWitheredPlant: Bool = false
    @AppStorage("debug_showGiveUpAlert") private var debugShowGiveUpAlert: Bool = false
    @AppStorage("debug_showCriticalHarvest") private var debugShowCriticalHarvest: Bool = false
    @AppStorage("debug_showAchievementUnlocked") private var debugShowAchievementUnlocked: Bool = false
    @AppStorage("debug_showHarvestRewards") private var debugShowHarvestRewards: Bool = false
    @AppStorage("debug_showProgressionRoot") private var debugShowProgressionRoot: Bool = false
    @AppStorage("debug_progressionAchievementsTab") private var debugProgressionAchievementsTab: Bool = false


    // SwiftData container for persisting sessions
    let container: ModelContainer

    init() {
        // ═══════════════════════════════════════════════════════════════
        // SwiftData Container Setup ONLY - no heavy operations here
        // ═══════════════════════════════════════════════════════════════
        let schema = Schema([
            FocusSession.self,
            UserProfile.self,
            Tag.self
        ])
        let modelConfiguration = ModelConfiguration(schema: schema, isStoredInMemoryOnly: false)
        
        do {
            container = try ModelContainer(for: schema, configurations: [modelConfiguration])
        } catch {
            print("Failed to initialize ModelContainer: \(error)")
            // Fallback: Delete the store and try again (Development only)
            let url = URL.applicationSupportDirectory.appending(path: "default.store")
            try? FileManager.default.removeItem(at: url)
            try? FileManager.default.removeItem(at: url.appendingPathExtension("shm"))
            try? FileManager.default.removeItem(at: url.appendingPathExtension("wal"))
            
            do {
                container = try ModelContainer(for: schema, configurations: [modelConfiguration])
            } catch {
                fatalError("Failed to initialize ModelContainer even after reset: \(error)")
            }
        }

        // MARK: - AppShots Debug Hooks for initial setup
        #if DEBUG
        setupDebugHooksInit()
        #endif
    }

    var body: some Scene {
        WindowGroup {
            ZStack {
            Group {
                if isOnboardingComplete {
                    GrowRoomView(initialTab: initialTab,
                                 debugShowPaywall: $debugShowPaywall,
                                 debugShowStrainSelection: $debugShowStrainSelection,
                                 debugShowBank: $debugShowBank,
                                 debugShowTagCreationSheet: $debugShowTagCreationSheet,
                                 debugShowResetAlert: $debugShowResetAlert,
                                 debugShowAboutAlert: $debugShowAboutAlert,
                                 debugShowTagManagement: $debugShowTagManagement,
                                 debugShowWitheredPlant: $debugShowWitheredPlant,
                                 debugShowGiveUpAlert: $debugShowGiveUpAlert,
                                 debugShowCriticalHarvest: $debugShowCriticalHarvest,
                                 debugShowAchievementUnlocked: $debugShowAchievementUnlocked,
                                 debugShowHarvestRewards: $debugShowHarvestRewards,
                                 debugShowProgressionRoot: $debugShowProgressionRoot,
                                 debugProgressionAchievementsTab: $debugProgressionAchievementsTab) // Pass debug flags
                } else {
                    OnboardingView(isOnboardingComplete: $isOnboardingComplete)
                }
            }
            .modelContainer(container)
            .onReceive(NotificationCenter.default.publisher(for: .didUpdateProStatus)) { notification in
                Task { @MainActor in
                    let context = container.mainContext
                    let descriptor = FetchDescriptor<UserProfile>()
                    if let profile = try? context.fetch(descriptor).first {
                        if let isPro = notification.object as? Bool {
                            profile.isPro = isPro
                            try? context.save()
                        }
                    }
                }
                }
                
                // Custom Launch Screen overlay
                if showLaunchScreen {
                    AppLaunchScreen()
                        .transition(.opacity)
                        .zIndex(1)
                }
            }
            .task {
                // MARK: - AppShots Debug Hooks (continued)
                #if DEBUG
                handleLaunchArgumentsTask()
                #endif

                // ═══════════════════════════════════════════════════════════════
                // FAST STARTUP: Don't block on network!
                // ═══════════════════════════════════════════════════════════════
                
                // 1. Fire off network tasks in background (don't await)
                Task { await RemoteConfigManager.shared.fetchConfig() }
                Task { await StoreManager.shared.loadProducts() }
                
                // 2. Pre-trigger lazy JSON loading (instant, local files)
                _ = Strain.allStrains
                _ = Achievement.allAchievements
                
                // 3. Brief visual polish delay, then hide splash
                // In DEBUG mode, this sleep is skipped if "-skip-splash" is present
                if CommandLine.arguments.contains("-skip-splash") {
                    // No sleep, hide immediately
                } else {
                    try? await Task.sleep(for: .milliseconds(300))
                }
                
                await MainActor.run {
                    withAnimation(.easeOut(duration: 0.3)) {
                        showLaunchScreen = false
                    }
                }
            }
        }
    }
}

#if DEBUG
// MARK: - AppShots Debug Hooks
extension PotodoroApp {
    private func setupDebugHooksInit() {
        // Clear all AppStorage debug flags on every app launch in DEBUG
        // to prevent persistent debug states influencing subsequent launches.
        // This includes all `debug_` prefixed keys AND core app keys that might interfere.
        let defaults = UserDefaults.standard
        defaults.dictionaryRepresentation().keys.forEach { key in
            if key.hasPrefix("debug_") || key.hasPrefix("session_") || key == "isOnboardingComplete" || key == "isDebugModeEnabled" || key == "hasEverRequestedNotificationPermission" || key == "cachedRemoteConfig" || key == "cachedRemoteConfigDate" {
                defaults.removeObject(forKey: key)
            }
        }
        
        // Ensure core state is reset
        isOnboardingComplete = false
        showLaunchScreen = true
        initialTab = nil

        // Clear SwiftData
        Task { @MainActor in
            let context = container.mainContext
            try? context.delete(model: FocusSession.self)
            try? context.delete(model: UserProfile.self)
            try? context.delete(model: Tag.self)

            // Seed default tags explicitly if deleted
            let growthVM = GrowthViewModel()
            growthVM.seedDefaultTags(context: context)
            
            // Create a default user profile to ensure one exists
            _ = growthVM.fetchOrCreateUserProfile(context: context)
        }

        // Process launch arguments for initial setup that happens early in app lifecycle
        handleLaunchArgumentsForEarlySetup()
    }

    private func handleLaunchArgumentsForEarlySetup() {
        let args = CommandLine.arguments
        let context = container.mainContext
        let growthVM = GrowthViewModel()

        if args.contains("-onboarding") {
            isOnboardingComplete = false
        } else {
            isOnboardingComplete = true // Default to true if not specifically testing onboarding
        }

        if let tabIndex = args.firstIndex(of: "-tab"),
           tabIndex + 1 < args.count,
           let tab = Int(args[tabIndex + 1]) {
            initialTab = tab
        }

        Task { @MainActor in
            var userProfile = growthVM.fetchOrCreateUserProfile(context: context)
            
            // Default user profile state for tests (can be overridden by specific args)
            userProfile.balance = 500
            userProfile.experiencePoints = 200
            userProfile.level = 2
            userProfile.unlockedStrainIds = ["blue_dream", "pineapple_express"]
            userProfile.passes3Day = 1
            userProfile.passes7Day = 0
            userProfile.passes14Day = 0
            userProfile.harvestCount = 3
            userProfile.totalYield = 50.0
            userProfile.isPro = false // Default to false
            userProfile.fertilizerExpiryDate = nil // Default to no fertilizer
            userProfile.unlockedAchievementIds = [] // Default to no achievements

            if args.contains("-pro-user") {
                userProfile.isPro = true
                NotificationCenter.default.post(name: .didUpdateProStatus, object: true)
            } else {
                userProfile.isPro = false
                NotificationCenter.default.post(name: .didUpdateProStatus, object: false)
                
                // For non-pro, limit custom tags for testing
                try? context.delete(model: Tag.self, predicate: #Predicate { !$0.isDefault })
                let tag1 = Tag(name: "Project X", colorHex: "#FF0000")
                let tag2 = Tag(name: "Client Call", colorHex: "#00FF00")
                context.insert(tag1)
                context.insert(tag2)
            }

            if args.contains("-debug-mode") {
                UserDefaults.standard.set(true, forKey: "isDebugModeEnabled")
            } else {
                UserDefaults.standard.set(false, forKey: "isDebugModeEnabled")
            }
            
            // RemoteConfig for sale banner
            if args.contains("-show-paywall-sale") {
                let saleConfig = SaleConfig(active: true, title: "FLASH SALE!", subtitle: "Lifetime PRO 50% OFF", endDate: ISO8601DateFormatter().string(from: Date().addingTimeInterval(3600*24*7)), badgeText: "HOT", salePrice: "$9.99", originalPrice: "$19.99")
                let remoteConfig = RemoteConfig(sale: saleConfig, announcements: .default, features: .default, version: .default)
                if let data = try? JSONEncoder().encode(remoteConfig) {
                    UserDefaults.standard.set(data, forKey: "cachedRemoteConfig")
                    UserDefaults.standard.set(Date(), forKey: "cachedRemoteConfigDate")
                }
            } else {
                // Ensure no sale config if not requested
                UserDefaults.standard.removeObject(forKey: "cachedRemoteConfig")
                UserDefaults.standard.removeObject(forKey: "cachedRemoteConfigDate")
            }

            // Session states are handled via GrowthViewModel's UserDefaults keys
            // These need to be cleared before setting new ones for a specific screen.
            GrowthViewModel().clearSessionState() // Clears kSessionActive etc.

            if args.contains("-session-active-timer") {
                defaults.set(true, forKey: "session_active")
                defaults.set(GrowthViewModel.SessionMode.timer.rawValue, forKey: "session_mode")
                defaults.set(Date().addingTimeInterval(15 * 60), forKey: "session_target_end") // 15 mins remaining
                defaults.set(25 * 60, forKey: "session_initial_duration") // Original 25 min timer
                defaults.set("blue_dream", forKey: "session_strain_id")
                defaults.set(false, forKey: "session_fertilizer_active_v2")
                // Particles for active session (example, actual particles are randomized and codable)
                let particles: [GrowthViewModel.Particle] = (0..<8).map { i in
                    GrowthViewModel.Particle(x: CGFloat.random(in: -70...70), y: CGFloat.random(in: -70...70), duration: Double.random(in: 1.5...2.5), delay: Double(i) * 0.1)
                }
                if let data = try? JSONEncoder().encode(particles) {
                    defaults.set(data, forKey: "session_fertilizer_particles")
                }
            } else if args.contains("-session-active-stopwatch") {
                defaults.set(true, forKey: "session_active")
                defaults.set(GrowthViewModel.SessionMode.stopwatch.rawValue, forKey: "session_mode")
                defaults.set(Date().addingTimeInterval(-180), forKey: "session_start_date") // 3 mins elapsed
                defaults.set("blue_dream", forKey: "session_strain_id")
                defaults.set(false, forKey: "session_fertilizer_active_v2")
            } else if args.contains("-session-harvest-ready") {
                defaults.set(true, forKey: "session_active")
                defaults.set(GrowthViewModel.SessionMode.timer.rawValue, forKey: "session_mode")
                defaults.set(Date().addingTimeInterval(-10), forKey: "session_target_end") // Ended 10 seconds ago
                defaults.set(25 * 60, forKey: "session_initial_duration")
                defaults.set("blue_dream", forKey: "session_strain_id")
                defaults.set(false, forKey: "session_fertilizer_active_v2")
                defaults.removeObject(forKey: "session_fertilizer_particles") // No particles for harvest ready
            }
            
            if args.contains("-fertilizer-active") {
                defaults.set(true, forKey: "session_fertilizer_active_v2")
                userProfile.fertilizerExpiryDate = Date().addingTimeInterval(3600 * 24 * 3) // 3 days
                // Generate particles
                let particles: [GrowthViewModel.Particle] = (0..<8).map { i in
                    GrowthViewModel.Particle(x: CGFloat.random(in: -70...70), y: CGFloat.random(in: -70...70), duration: Double.random(in: 1.5...2.5), delay: Double(i) * 0.1)
                }
                if let data = try? JSONEncoder().encode(particles) {
                    defaults.set(data, forKey: "session_fertilizer_particles")
                }
            } else {
                defaults.set(false, forKey: "session_fertilizer_active_v2")
                defaults.removeObject(forKey: "session_fertilizer_particles")
                userProfile.fertilizerExpiryDate = nil
            }

            // Data population
            if args.contains("-add-focus-sessions") {
                // Clear existing sessions for predictable debug data
                try? context.delete(model: FocusSession.self)
                
                // Add some sessions
                let blueDream = Strain.allStrains.first(where: { $0.id == "blue_dream" })!
                let pineappleExpress = Strain.allStrains.first(where: { $0.id == "pineapple_express" })!
                
                let session1 = FocusSession(strainId: blueDream.id, durationMinutes: 25)
                session1.endTime = Date().addingTimeInterval(-3600 * 24 * 2) // 2 days ago
                session1.status = .completed
                session1.calculateEarnings()
                context.insert(session1)
                
                let session2 = FocusSession(strainId: pineappleExpress.id, durationMinutes: 45)
                session2.endTime = Date().addingTimeInterval(-3600 * 24 * 1) // 1 day ago
                session2.status = .completed
                session2.calculateEarnings()
                context.insert(session2)
                
                let session3 = FocusSession(strainId: blueDream.id, durationMinutes: 30)
                session3.endTime = Date().addingTimeInterval(-3600) // 1 hour ago
                session3.status = .completed
                session3.calculateEarnings()
                context.insert(session3)
            } else {
                // Clear sessions if not explicitly requested
                try? context.delete(model: FocusSession.self)
            }

            // Achievements setup
            if args.contains("-achievement-unlocked") {
                userProfile.unlockedAchievementIds = ["first_harvest"]
            } else {
                userProfile.unlockedAchievementIds = []
            }
            
            try? context.save()
        }
    }

    private func handleLaunchArgumentsTask() {
        let args = CommandLine.arguments
        
        // These AppStorage flags are observed by GrowRoomView and its children to trigger UI
        UserDefaults.standard.set(args.contains("-show-paywall"), forKey: "debug_showPaywall")
        UserDefaults.standard.set(args.contains("-show-strain-selection"), forKey: "debug_showStrainSelection")
        UserDefaults.standard.set(args.contains("-show-bank"), forKey: "debug_showBank")
        UserDefaults.standard.set(args.contains("-show-tags"), forKey: "debug_showTagCreationSheet")
        UserDefaults.standard.set(args.contains("-show-reset-alert"), forKey: "debug_showResetAlert")
        UserDefaults.standard.set(args.contains("-about-app"), forKey: "debug_showAboutAlert")
        UserDefaults.standard.set(args.contains("-manage-tags"), forKey: "debug_showTagManagement")
        UserDefaults.standard.set(args.contains("-show-withered-plant"), forKey: "debug_showWitheredPlant")
        UserDefaults.standard.set(args.contains("-show-give-up-alert"), forKey: "debug_showGiveUpAlert")
        UserDefaults.standard.set(args.contains("-critical-harvest"), forKey: "debug_showCriticalHarvest")
        UserDefaults.standard.set(args.contains("-achievement-unlocked"), forKey: "debug_showAchievementUnlocked")
        UserDefaults.standard.set(args.contains("-harvest-rewards"), forKey: "debug_showHarvestRewards")
        UserDefaults.standard.set(args.contains("-show-progression-milestones") || args.contains("-show-progression-achievements"), forKey: "debug_showProgressionRoot")
        UserDefaults.standard.set(args.contains("-show-progression-achievements"), forKey: "debug_progressionAchievementsTab")
        
        // This is a special flag to force the splash screen to disappear *immediately* after setup,
        // allowing AppShots to control the `wait_seconds` for the splash screen itself.
        if args.contains("-skip-splash") {
            showLaunchScreen = false
        }
    }
}
#endif

// Add to Potodoro/Potodoro/Views/Screens/GrowRoomView.swift (modify existing struct)
struct GrowRoomView: View {
    @StateObject private var viewModel = GrowthViewModel()
    @State private var selectedTab: Int // Initialized below
    @Environment(\.modelContext) private var modelContext
    
    // MARK: - AppShots Debug Flags (Bindings from App)
    @Binding var debugShowPaywall: Bool
    @Binding var debugShowStrainSelection: Bool
    @Binding var debugShowBank: Bool
    @Binding var debugShowTagCreationSheet: Bool
    @Binding var debugShowResetAlert: Bool
    @Binding var debugShowAboutAlert: Bool
    @Binding var debugShowTagManagement: Bool
    @Binding var debugShowWitheredPlant: Bool
    @Binding var debugShowGiveUpAlert: Bool
    @Binding var debugShowCriticalHarvest: Bool
    @Binding var debugShowAchievementUnlocked: Bool
    @Binding var debugShowHarvestRewards: Bool
    @Binding var debugShowProgressionRoot: Bool
    @Binding var debugProgressionAchievementsTab: Bool

    // Initializer to accept debug flags and initial tab
    init(initialTab: Int?,
         debugShowPaywall: Binding<Bool>,
         debugShowStrainSelection: Binding<Bool>,
         debugShowBank: Binding<Bool>,
         debugShowTagCreationSheet: Binding<Bool>,
         debugShowResetAlert: Binding<Bool>,
         debugShowAboutAlert: Binding<Bool>,
         debugShowTagManagement: Binding<Bool>,
         debugShowWitheredPlant: Binding<Bool>,
         debugShowGiveUpAlert: Binding<Bool>,
         debugShowCriticalHarvest: Binding<Bool>,
         debugShowAchievementUnlocked: Binding<Bool>,
         debugShowHarvestRewards: Binding<Bool>,
         debugShowProgressionRoot: Binding<Bool>,
         debugProgressionAchievementsTab: Binding<Bool>
    ) {
        _selectedTab = State(initialValue: initialTab ?? 1) // Default to Dashboard (center)
        _debugShowPaywall = debugShowPaywall
        _debugShowStrainSelection = debugShowStrainSelection
        _debugShowBank = debugShowBank
        _debugShowTagCreationSheet = debugShowTagCreationSheet
        _debugShowResetAlert = debugShowResetAlert
        _debugShowAboutAlert = debugShowAboutAlert
        _debugShowTagManagement = debugShowTagManagement
        _debugShowWitheredPlant = debugShowWitheredPlant
        _debugShowGiveUpAlert = debugShowGiveUpAlert
        _debugShowCriticalHarvest = debugShowCriticalHarvest
        _debugShowAchievementUnlocked = debugShowAchievementUnlocked
        _debugShowHarvestRewards = debugShowHarvestRewards
        _debugShowProgressionRoot = debugShowProgressionRoot
        _debugProgressionAchievementsTab = debugProgressionAchievementsTab
    }
    
    var body: some View {
        ZStack {
            // Global "Breathing" Background
            BreathingBackgroundView(colors: backgroundColorsForTab(selectedTab))
                .animation(.easeInOut(duration: 0.5), value: selectedTab)
                .fontDesign(.rounded)
            
            TabView(selection: $selectedTab) {
                ZStack {
                    // Transparent bg to let breathing view show through
                    Color.clear 
                    NavigationStack {
                        SettingsView(viewModel: viewModel, 
                                     debugShowPaywall: $debugShowPaywall, 
                                     debugShowResetAlert: $debugShowResetAlert,
                                     debugShowAboutAlert: $debugShowAboutAlert,
                                     debugShowTagManagement: $debugShowTagManagement,
                                     debugShowProgressionRoot: $debugShowProgressionRoot,
                                     debugProgressionAchievementsTab: $debugProgressionAchievementsTab
                        ) // Pass debug flags
                    }
                }
                .tag(0)
                
                GrowRoomDashboard(viewModel: viewModel, selectedTab: $selectedTab, 
                                  debugShowPaywall: $debugShowPaywall, 
                                  debugShowStrainSelection: $debugShowStrainSelection, 
                                  debugShowBank: $debugShowBank,
                                  debugShowTagCreationSheet: $debugShowTagCreationSheet,
                                  debugShowWitheredPlant: $debugShowWitheredPlant,
                                  debugShowGiveUpAlert: $debugShowGiveUpAlert,
                                  debugShowCriticalHarvest: $debugShowCriticalHarvest,
                                  debugShowAchievementUnlocked: $debugShowAchievementUnlocked,
                                  debugShowHarvestRewards: $debugShowHarvestRewards
                ) // Pass debug flags
                    .tag(1)
                
                ZStack {
                    // Transparent bg
                    Color.clear
                    StashView(onDismiss: {
                        withAnimation(.easeInOut(duration: 0.25)) { selectedTab = 1 }
                    }, debugShowPaywall: $debugShowPaywall) // Pass debug flags
                }
                .tag(2)
            }
            .tabViewStyle(.page(indexDisplayMode: .never))
            .ignoresSafeArea()
            
            // --- Overlays using debug flags ---
            // Priority: Critical Harvest > Achievements > Harvest Rewards > Withered > GiveUp
            if debugShowCriticalHarvest {
                CriticalHarvestView(
                    coins: viewModel.lastHarvestCoins == 0 ? 100 : viewModel.lastHarvestCoins, // Default if not set by session
                    xp: viewModel.lastHarvestXP == 0 ? 200 : viewModel.lastHarvestXP,
                    onDismiss: {
                    withAnimation {
                        debugShowCriticalHarvest = false
                        // Critical harvest already shows rewards, skip the regular animation
                        debugShowHarvestRewards = false
                    }
                    }
                )
                .zIndex(100)
            } else if debugShowAchievementUnlocked {
                AchievementUnlockedView(achievement: Achievement.allAchievements.first!, onDismiss: { // Use first achievement for debug
                    withAnimation {
                        debugShowAchievementUnlocked = false
                    }
                })
                .zIndex(100)
            } else if debugShowHarvestRewards {
                // Shows after critical/achievements are dismissed (or if neither triggered)
                HarvestRewardsView(
                    coins: viewModel.lastHarvestCoins == 0 ? 50 : viewModel.lastHarvestCoins,
                    xp: viewModel.lastHarvestXP == 0 ? 100 : viewModel.lastHarvestXP,
                    onComplete: {
                        debugShowHarvestRewards = false
                    }
                )
                .zIndex(99)
            }
            
            // Withered plant overlay - shown when user gives up
            if debugShowWitheredPlant {
                WitheredPlantView(
                    strainName: viewModel.witheredStrainName.isEmpty ? "Blue Dream" : viewModel.witheredStrainName, // Default strain
                    salvageCoins: viewModel.salvageCoinsEarned == 0 ? 15 : viewModel.salvageCoinsEarned,
                    onDismiss: {
                        debugShowWitheredPlant = false
                        viewModel.dismissWitheredPlant() // Resets GrowthViewModel internal state
                    }
                )
                .zIndex(100)
            }
            
            if debugShowGiveUpAlert {
                GiveUpAlertView(
                    isPresented: $debugShowGiveUpAlert, // Bind to debug flag
                    viewModel: viewModel,
                    modelContext: modelContext
                )
                .zIndex(101)
            }
        }
    }
    
    func backgroundColorsForTab(_ tab: Int) -> [Color] {
        switch tab {
        case 0: // Settings (Dark Space Theme)
            return [Color(hex: "0B1013"), Color(hex: "1C2833"), Color(hex: "0B1013")]
        case 1: // Grow Room (Lush Green Theme)
            return [Color(hex: "546A36"), Color(hex: "6B9440"), Color(hex: "546A36")]
        case 2: // Stash (Industrial Dark Warehouse)
            return [Color(hex: "1C2833"), Color(hex: "2C3545"), Color(hex: "1C2833")]
        default:
            return [Color.black]
        }
    }
}

// Add to Potodoro/Potodoro/Views/Screens/GrowRoomView.swift (Modify existing GrowRoomDashboard)
struct GrowRoomDashboard: View {
    @Environment(\.modelContext) private var modelContext
    @Environment(\.scenePhase) var scenePhase
    @Query private var userProfiles: [UserProfile]
    @ObservedObject var viewModel: GrowthViewModel
    @Binding var selectedTab: Int
    
    @State private var showSelectionSheet = false
    @State private var showBankSheet = false
    // showGiveUpAlert moved to ViewModel
    @State private var showMilestones = false // Will use ProgressionRootView instead
    @State private var showPaywall = false // Used for actual app, but debug flag overrides
    @State private var showLoadingAnimation = false
    
    // MARK: - AppShots Debug Flags (Bindings from GrowRoomView)
    @Binding var debugShowPaywall: Bool
    @Binding var debugShowStrainSelection: Bool
    @Binding var debugShowBank: Bool
    @Binding var debugShowTagCreationSheet: Bool
    @Binding var debugShowWitheredPlant: Bool
    @Binding var debugShowGiveUpAlert: Bool
    @Binding var debugShowCriticalHarvest: Bool
    @Binding var debugShowAchievementUnlocked: Bool
    @Binding var debugShowHarvestRewards: Bool

    let oliveGreen = Color(hex: "546A36")
    let lightGreen = Color(hex: "8DB654")
    let navyBlue = Color(hex: "2C3545")
    
    var body: some View {
        let userProfile = userProfiles.first ?? UserProfile()

        // MARK: - AppShots Debug Flag Observers
        .onChange(of: debugShowPaywall) { _, newValue in showPaywall = newValue }
        .onChange(of: debugShowStrainSelection) { _, newValue in showSelectionSheet = newValue }
        .onChange(of: debugShowBank) { _, newValue in showBankSheet = newValue }
        .onChange(of: debugShowGiveUpAlert) { _, newValue in viewModel.showGiveUpAlert = newValue } // Directly to ViewModel's @Published
        // ... (other onChange for overlays are handled directly in GrowRoomView)
        // ... rest of the view content ...
        .sheet(isPresented: $showSelectionSheet) { // Use local state
            StrainSelectionSheet(viewModel: viewModel, debugShowTagCreationSheet: $debugShowTagCreationSheet, debugShowPaywall: $debugShowPaywall)
                .presentationDetents([.fraction(0.95)])
        }
        .sheet(isPresented: $showBankSheet) { // Use local state
            BankView()
                .presentationDetents([.large])
        }
        .sheet(isPresented: $showPaywall) { // Use local state
            PaywallView()
        }
    }
}

// Add to Potodoro/Potodoro/Views/Screens/SettingsView.swift (Modify existing SettingsView)
struct SettingsView: View {
    @Environment(\.dismiss) var dismiss
    @Environment(\.modelContext) private var modelContext
    @Environment(\.requestReview) var requestReview
    @Query private var userProfiles: [UserProfile]
    
    @ObservedObject var viewModel: GrowthViewModel
    
    @AppStorage("isStrictMode") private var isStrictMode = false
    @AppStorage("hapticsEnabled") private var hapticsEnabled = true
    @AppStorage("liveActivitiesEnabled") private var liveActivitiesEnabled = false
    @AppStorage("isDebugModeEnabled") private var isDebugModeEnabled = false
    @State private var versionTapCount = 0
    
    @State private var showResetAlert = false // Local state
    @State private var showExportAlert = false // Local state
    @State private var showPaywall = false // Local state
    @State private var showAboutAlert = false // Local state
    @State private var showTagManagement = false // Local state
    @State private var showLiveActivityPermissionAlert = false
    @State private var showProgressionRoot = false // Local state for ProgressionRootView
    @State private var progressionAchievementsTab = false // Local state for ProgressionRootView's initial tab
    
    // MARK: - AppShots Debug Flags (Bindings from GrowRoomView)
    @Binding var debugShowPaywall: Bool
    @Binding var debugShowResetAlert: Bool
    @Binding var debugShowAboutAlert: Bool
    @Binding var debugShowTagManagement: Bool
    @Binding var debugShowProgressionRoot: Bool
    @Binding var debugProgressionAchievementsTab: Bool

    // Colors
    let bg = Color(hex: "0B1013") // Deep Dark Base
    let cardBg = Color(hex: "1C2833").opacity(0.8) // Dark Panel
    let oliveGreen = Color(hex: "546A36")
    let navyBlue = Color(hex: "2C3545")
    let textPrimary = Color.white
    let textSecondary = Color(hex: "BDC3C7")
    
    // Custom gradient divider component
    private var GradientDivider: some View {
        Rectangle()
            .fill(
                LinearGradient(
                    colors: [
                        Color.white.opacity(0),
                        Color.white.opacity(0.15),
                        Color.white.opacity(0.3),
                        Color.white.opacity(0.15),
                        Color.white.opacity(0)
                    ],
                    startPoint: .leading,
                    endPoint: .trailing
                )
            )
            .frame(height: 1)
    }
    

    var body: some View {
        let userProfile = userProfiles.first ?? UserProfile()
        ZStack {
            // MARK: - AppShots Debug Flag Observers
            .onChange(of: debugShowPaywall) { _, newValue in showPaywall = newValue }
            .onChange(of: debugShowResetAlert) { _, newValue in showResetAlert = newValue }
            .onChange(of: debugShowAboutAlert) { _, newValue in showAboutAlert = newValue }
            .onChange(of: debugShowTagManagement) { _, newValue in showTagManagement = newValue }
            .onChange(of: debugShowProgressionRoot) { _, newValue in showProgressionRoot = newValue }
            .onChange(of: debugProgressionAchievementsTab) { _, newValue in progressionAchievementsTab = newValue }

            // ... rest of the view content ...
            .fullScreenCover(isPresented: $showPaywall) { // Use local state
                PaywallView()
            }
            .customModal(isPresented: $showResetAlert, config: resetAlertConfig) // Use local state
            .customModal(isPresented: $showAboutAlert, config: aboutAlertConfig) // Use local state
            .customSlidePanel(isPresented: $showTagManagement, edge: .trailing) { // Use local state
                TagManagementPanel()
            }
            .fullScreenCover(isPresented: $showProgressionRoot) { // Use local state
                if let profile = userProfiles.first {
                    ProgressionRootView(userProfile: profile, initialTab: progressionAchievementsTab ? 1 : 0)
                }
            }
        }
    }
    // ... rest of the SettingsView logic
}

// Add to Potodoro/Potodoro/Views/Screens/StashView.swift (Modify existing StashView)
struct StashView: View {
    @Query(sort: \FocusSession.startTime, order: .reverse) private var sessions: [FocusSession]
    @Query private var tags: [Tag]
    @Query private var userProfiles: [UserProfile]
    var onDismiss: () -> Void
    @Environment(\.modelContext) private var modelContext
    @State private var dragOffset: CGFloat = 0
    @State private var isExpanded: Bool = false
    @State private var selectedTimeFrame: TimeFrame = .day
    @State private var currentDate = Date()
    @State private var selectedSession: FocusSession?
    @State private var showPaywall = false // Local state

    // MARK: - AppShots Debug Flags (Binding from GrowRoomView)
    @Binding var debugShowPaywall: Bool
    
    // Constants for sheet positions
    private let collapsedHeight: CGFloat = 120
    private let expandedHeight: CGFloat = 550
    
    var body: some View {
        ZStack {
            // MARK: - AppShots Debug Flag Observer
            .onChange(of: debugShowPaywall) { _, newValue in showPaywall = newValue }
            // ... rest of the view content ...
            .sheet(isPresented: $showPaywall) { // Use local state
                PaywallView()
            }
        }
    }
    // ... rest of the StashView logic
}

// Add to Potodoro/Potodoro/Views/Screens/StrainSelectionSheet.swift (Modify existing StrainSelectionSheet)
struct StrainSelectionSheet: View {
    @Environment(\.dismiss) var dismiss
    @Environment(\.modelContext) private var modelContext
    @ObservedObject var viewModel: GrowthViewModel
    
    @Query private var userProfiles: [UserProfile]
    @Query private var tags: [Tag]
    
    @State private var showPurchaseAlert = false
    @State private var showBankSheet = false
    @State private var showTagCreationSheet = false // Local state
    @State private var showPaywall = false // Local state
    @State private var selectedStrainToBuy: Strain?
    @State private var pendingStrain: Strain? // Temp storage for paywall flow
    
    // MARK: - AppShots Debug Flags (Bindings from GrowRoomDashboard)
    @Binding var debugShowTagCreationSheet: Bool
    @Binding var debugShowPaywall: Bool

    var rows: [GridItem] {
        let size = AdaptiveSize.StrainSelection.gridItemSize
        let spacing = AdaptiveSize.StrainSelection.gridSpacing
        return [
            GridItem(.fixed(size), spacing: spacing),
            GridItem(.fixed(size), spacing: spacing)
        ]
    }
    
    var body: some View {
        let userProfile = userProfiles.first ?? UserProfile()
        
        ZStack {
            // MARK: - AppShots Debug Flag Observers
            .onChange(of: debugShowTagCreationSheet) { _, newValue in showTagCreationSheet = newValue }
            .onChange(of: debugShowPaywall) { _, newValue in showPaywall = newValue }
            // ... rest of the view content ...
            .customBottomSheet(isPresented: $showTagCreationSheet, snapPoints: [0.5]) { // Use local state
                TagCreationSheet()
                    .clipShape(RoundedRectangle(cornerRadius: 24))
            }
            .sheet(isPresented: $showPaywall, onDismiss: { // Use local state
                // Check if they bought Pro
                if userProfile.isPro {
                    // If they became Pro, unlock pending strain for free
                    if let strain = pendingStrain {
                        userProfile.unlockedStrainIds.append(strain.id)
                        viewModel.selectedStrain = strain
                        try? modelContext.save()
                        pendingStrain = nil
                    }
                } else {
                    // If still Basic, show the coin purchase alert
                    if let strain = pendingStrain {
                        selectedStrainToBuy = strain
                        pendingStrain = nil
                    }
                }
            }) {
                PaywallView()
            }
        }
    }
}

// Add to Potodoro/Potodoro/Views/Screens/ProgressionRootView.swift (Modify existing ProgressionRootView)
struct ProgressionRootView: View {
    @Environment(\.dismiss) var dismiss
    let userProfile: UserProfile
    @State private var selectedTab: Int // Initialized below

    init(userProfile: UserProfile, initialTab: Int = 0) {
        self.userProfile = userProfile
        _selectedTab = State(initialValue: initialTab)
    }
    
    var body: some View {
        ZStack {
            Color(hex: "0B1013").ignoresSafeArea()
            
            VStack(spacing: 0) {
                // Custom Tab Bar
                HStack {
                    Button(action: { withAnimation { selectedTab = 0 } }) {
                        VStack(spacing: 4) {
                            Text("Growth Path")
                                .font(.headline)
                                .foregroundStyle(selectedTab == 0 ? .white : .gray)
                            Capsule()
                                .fill(selectedTab == 0 ? Color(hex: "8DB654") : Color.clear)
                                .frame(height: 3)
                        }
                    }
                    .frame(maxWidth: .infinity)
                    
                    Button(action: { withAnimation { selectedTab = 1 } }) {
                        VStack(spacing: 4) {
                            Text("Achievements")
                                .font(.headline)
                                .foregroundStyle(selectedTab == 1 ? .white : .gray)
                            Capsule()
                                .fill(selectedTab == 1 ? Color(hex: "8DB654") : Color.clear)
                                .frame(height: 3)
                        }
                    }
                    .frame(maxWidth: .infinity)
                    
                    // Close Button
                    Button(action: { dismiss() }) {
                        Image(systemName: "xmark.circle.fill")
                            .font(.title2)
                            .foregroundStyle(.gray)
                    }
                    .padding(.leading, 8)
                }
                .padding()
                .background(Color(hex: "1C2833"))
                
                TabView(selection: $selectedTab) {
                    MilestonePathView(userLevel: userProfile.level, showHeader: false)
                        .tag(0)
                    
                    AchievementsView(userProfile: userProfile)
                        .tag(1)
                }
                .tabViewStyle(.page(indexDisplayMode: .never))
            }
        }
    }
}