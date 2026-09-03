# Plant Catalogue Features

This page provides a detailed overview of all features in the Dog-Safe Garden Plants section.

## 🌿 Overview of Features

### Core Features (Always Available)

#### 1. **Plant Catalogue**
- Browse 609 dog-safe plants
- High-quality images for most plants
- Detailed plant descriptions
- Safety status indicators
- Scientific names
- Care information

#### 2. **Search & Discovery**
- Text search (by name or scientific name)
- Fuzzy search (finds similar names)
- Category filtering (flowers, herbs, vegetables, etc.)
- Safety status filtering
- Season filtering
- Tree/non-tree toggle
- Climate zone filtering (UK hardiness)

#### 3. **Plant Profiles**
Click any plant to view:
- Full plant description
- Detailed care requirements
- Water needs
- Light requirements
- Soil preferences
- Mature size/height
- Growth habit
- Seasonal information
- ASPCA source link
- Multiple images (if available)

#### 4. **Favorites System**
- Star plants you like
- View all favorites in one place
- Export favorites as CSV
- Persistent storage (saved locally)

#### 5. **Plant Library**
Track plants you're growing:
- Add plants to your personal garden
- Set location (e.g., "Front border")
- Track health status
- Add personal notes
- Auto-generated care reminders
- Export library as CSV

#### 6. **Care Schedule**
Monitor plant care tasks:
- Watering reminders
- Fertilizing schedules
- Pruning dates
- Health checks
- Mark tasks complete
- Automatic rescheduling

#### 7. **Climate Zone Filtering**
Find plants for your location:
- Enter UK postcode
- Auto-detect hardiness zone
- See only suitable plants
- Understand cold/heat tolerance
- Plan for seasonal changes

#### 8. **AI Garden Planner**
Get personalized recommendations:
- Answer simple questions about your garden
- Receive plant suggestions
- Get layout tips
- Learn companion planting
- View care guidelines
- All recommendations are dog-safe

#### 9. **Dark Mode**
- Toggle dark theme
- Reduces eye strain
- Preference saved
- Works on all pages

#### 10. **Image Management** (Admin)
- Find missing plant images
- Search Wikimedia Commons
- Search iNaturalist
- Approve/reject images
- Batch update images
- Quality scoring system

---

## 📊 Feature Comparison Table

| Feature | Availability | Save Data? | Export? |
|---------|--------------|-----------|---------|
| Browse Catalogue | Always | No | No |
| Search Plants | Always | No | No |
| View Plant Profiles | Always | No | No |
| Star Favorites | Always | Yes (Local) | CSV |
| My Plant Library | Always | Yes (Local) | CSV |
| Care Schedule | With Library | Yes (Local) | With Library |
| Climate Zone Filter | Always | Yes (Local) | N/A |
| AI Garden Planner | Always | No | Manually copy |
| Dark Mode | Always | Yes (Local) | N/A |
| Image Management | Admin Only | N/A | N/A |

---

## 🔧 Technical Details

### Data Storage
- **Favorites**: Browser's localStorage
- **Plant Library**: Browser's localStorage
- **Care Tasks**: Browser's localStorage
- **Dark Mode**: Browser's localStorage
- **Climate Zone**: Browser's localStorage

### Performance
- **Total Plants**: 609
- **Plants per Page**: 12 (pagination)
- **Load Time**: ~2-3 seconds
- **Image Loading**: Lazy loading (loads as you scroll)
- **Search**: Real-time, instant results

### Browser Compatibility
- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+
- Mobile browsers (iOS Safari, Chrome Mobile)

### Data Privacy
- All data stored locally on your device
- No data sent to external servers (except image searches)
- No personal information collected
- Export your data anytime

---

## 🎯 Feature Deep Dives

### Search Capabilities

#### Text Search
- **How**: Type plant name or scientific name
- **Speed**: Instant (as you type)
- **Coverage**: Searches across:
  - Common names
  - Scientific names
  - Descriptions
  - Categories
- **Fuzzy matching**: Finds similar words
- **Example searches**:
  - "rose" → finds all roses
  - "Rosa" → finds scientific names
  - "lavender" → finds Lavenders
  - "poison" → finds description with word

#### Category Filter
- **Categories**: Flowers, Herbs, Vegetables, Fruit, Grasses
- **Multiple select**: Choose multiple categories
- **Combination**: Works with other filters
- **Result**: Shows only plants in selected categories

#### Safety Filter
- **Levels**: 
  - Non-toxic to dogs (safe)
  - May be Toxic (caution)
  - Toxic (danger)
- **Uses**: Filter by safety level or see all
- **Combined**: Works with other filters

#### Season Filter
- **Seasons**: Spring, Summer, Autumn, Winter
- **Bloom time**: When plant flowers/looks best
- **Uses**: Plan seasonal color/interest
- **Combined**: Works with all other filters

### Favorites System

#### How Favorites Work
1. Click ⭐ star on any plant card
2. Plant is saved to your favorites
3. Star button fills in (shows it's favorited)
4. Switch to "My Favorites" tab to see all
5. Favorites are sorted alphabetically
6. Click star again to unfavorite

#### Exporting Favorites
1. Go to "My Favorites" tab
2. Click "Export CSV" button
3. File downloads as `my-plant-library.csv`
4. Open in Excel/Google Sheets
5. Columns: Name, Scientific Name, Category, Safety Status

### Plant Library Features

#### Adding Plants
1. Click "+ Add Plant" button
2. Search for plant by name
3. Click plant in results
4. Fill in:
   - **Location**: Where it's planted
   - **Health Status**: Current condition
   - **Notes**: Your observations
5. Click "Save Plant"
6. Watering reminder created automatically

#### Tracking Health
- **Healthy**: Plant is thriving
- **Needs Attention**: Plant has issues
- **Recovering**: Plant is bouncing back
- Add notes about what you observe
- Update status as plant changes

#### Care Reminders
- **Auto-created**: 7-day watering cycle
- **Customizable**: Change frequency
- **Multiple reminders**: Add pruning, fertilizing, etc.
- **Track completion**: Check off when done
- **Auto-reschedule**: Next date calculated automatically

#### Exporting Library
1. Go to "My Plant Library" tab
2. Click "Export CSV" button
3. Downloads: `my-garden-library.csv`
4. Columns: Name, Location, Health, Notes
5. Use for backup or import elsewhere

### Climate Zone Feature

#### How It Works
1. Enter your UK postcode
2. System determines your hardiness zone
3. Plants auto-filter to suitable ones
4. Your zone is displayed
5. Only compatible plants shown
6. Can be cleared with "Clear filters"

#### Hardiness Zones Explained

**H1-H3** (Warmest)
- Southwest England, Channel Islands, coastal areas
- Can grow tender/tropical plants
- Limited frost risk

**H4** (Mild)
- Most of England, southern Wales
- Can grow most garden plants
- Some winter protection needed for tender plants

**H5** (Cool)
- North England, northern Wales
- Hardy plants preferred
- Winter temperatures -5 to 0°C

**H6** (Very Cold)
- Scotland, northern regions
- Need very hardy plants
- Winter temperatures -10 to -5°C

**H7** (Extreme)
- Far northern Scotland
- Only extreme hardy plants survive
- Winter temperatures below -10°C

#### Plant Hardiness Information
Each plant shows:
- **Zones**: e.g., "H3-H7" (grows in zones 3-7)
- **Min Temp**: Lowest it tolerates
- **Max Temp**: Highest it tolerates
- **Info**: Will it survive year-round in your zone?

### AI Garden Planner

#### How It Works
1. Visit AI Garden Planner page
2. Answer questions about your garden:
   - Garden size (Small/Medium/Large)
   - Sunlight (Full Sun/Partial Shade/Shade)
   - Soil type (Clay/Sandy/Loamy/Mixed)
   - UK postcode (auto-detects zone)
   - Preferences (Flowers/Herbs/Vegetables/Low-maintenance)
3. Click "Get Recommendations"
4. Receive personalized suggestions:
   - 10-15 suitable plants
   - Layout/arrangement tips
   - Companion planting suggestions
   - General care advice
   - Dog safety confirmation

#### Recommendation Quality
- All suggestions are verified dog-safe
- Plants match your specific conditions
- Combinations work well together
- Practical care advice included
- Suitable for your climate zone

### Care Schedule

#### Task Types
- **Watering**: Most frequent (7-14 days)
- **Fertilizing**: Seasonal (monthly/quarterly)
- **Pruning**: Seasonal (spring/summer)
- **Health Check**: Monthly inspection
- **Deadheading**: As needed during blooming

#### Task Display
- **Overdue**: Red (do immediately)
- **Due This Week**: Orange (plan this week)
- **Upcoming**: Blue (coming soon)
- **Sorted by**: Due date then plant name

#### Completing Tasks
1. View Care Schedule section
2. Click on task you want to complete
3. Task details appear
4. Click "Mark Complete"
5. Next occurrence auto-scheduled
6. Task moves to future dates

### Image Management (Admin Feature)

#### What It Does
- Finds high-quality plant images
- Searches Wikimedia Commons
- Searches iNaturalist API
- Scores image quality
- Allows admin to approve/reject
- Batch updates multiple plants

#### Quality Scoring
Considers:
- Resolution (high res = better)
- Clarity/sharpness
- Lighting/exposure
- Relevance to plant
- License/attribution
- Professional quality

#### How to Use (Admin)
1. Go to Plant Settings
2. Click "Find Missing Photos"
3. Select plant
4. View candidate images
5. See image details (source, size, quality score)
6. Click "Approve" to use
7. Click "Reject" to skip
8. Selected image updates plant profile

---

## 🚀 Performance Tips

### Faster Browsing
- **Use Search**: Faster than scrolling through pagination
- **Apply Filters**: Narrows results quickly
- **Favorites**: Quick access to plants you like
- **Climate Zone**: Reduces results significantly

### Better Results
- **Be specific**: Search for exact plant names
- **Use Filters**: Combine multiple filters for precision
- **Check profiles**: Read full details before deciding
- **Look at images**: Visual confirmation helps

### Data Management
- **Export regularly**: Back up your library
- **Organize notes**: Use location notes to organize
- **Update status**: Keep health status current
- **Review tasks**: Check care schedule weekly

---

## ⚡ Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+F` | Browser find (search current page) |
| `Tab` | Navigate between elements |
| `Enter` | Submit/Confirm actions |
| `Esc` | Close modals/popups |

---

## 🆘 Troubleshooting

### Plants Not Showing?
- Check filters aren't too restrictive
- Try clearing all filters
- Search for specific plant
- Check "Hide Trees" isn't ON

### Images Not Loading?
- Check internet connection
- Click "Find correct photo" for that plant
- Try refreshing the page
- Check browser cache

### Data Not Saving?
- Check browser allows localStorage
- Clear browser cookies/cache
- Try different browser
- Check you're not in private mode

### Slow Performance?
- Try closing other browser tabs
- Clear browser cache
- Reduce number of filters
- Use pagination instead of showing all

---

## 📱 Mobile Features

### Responsive Design
- Automatically adjusts for mobile/tablet
- Smaller images on small screens
- Vertical layout on mobile
- Large touch targets for buttons

### Mobile-Specific
- Shorter pagination (3 pages shown vs 5)
- Swipe support coming soon
- Mobile-optimized modals
- Faster loading on cellular

---

## 🔜 Upcoming Features

- Cloud sync for plant library
- Mobile app (iOS/Android)
- Plant identification via camera
- Seasonal planting calendar
- Community gardens map
- Plant sourcing (nurseries/sellers)
- Advanced care scheduling
- Photo upload for custom plants

---

**Last Updated**: August 2026
