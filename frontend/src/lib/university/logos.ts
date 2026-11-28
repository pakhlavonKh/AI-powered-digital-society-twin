/**
 * University logo registry for the Programs explorer.
 *
 * Keyed by the official ÖSYM institution code (University.official_university_code: the four-digit prefix shared by
 * every program code of one university). A logo is listed here only when all three are confirmed: the institution
 * match, a recorded asset source, and published terms that allow this reuse. Anything else renders the neutral fallback.
 *
 * Entries come from Wikimedia Commons files tagged public domain as text logos (below the threshold of originality),
 * each checked visually as a plain wordmark or simple mark of that institution. Official brand guides checked so far
 * publish no third-party grant, so they are not a source here. Logos remain trademarks of their institutions and are
 * shown only to identify the institution beside its name. Sourcing records live in the git-ignored local checklist.
 */
export type LogoAsset = {
  /** Same-origin path under /university-logos/, never a hotlinked third-party URL. */
  src: string;
  /** Official variant for dark backgrounds, when the institution publishes one. */
  srcDark?: string;
  /** Intrinsic size of the asset, so the proportions are preserved. */
  width: number;
  height: number;
  institution: string;
  /** Page the asset file was taken from (its license page). */
  sourceUrl: string;
  /** Published usage terms or written permission that covers this use. */
  terms: string;
};

export const VERIFIED_LOGOS: Readonly<Record<string, LogoAsset>> = Object.freeze({
  "1010": { src: "/university-logos/1010.png", width: 589, height: 304, institution: "Anadolu Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Anadolu_University_Logo.png",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "1018": { src: "/university-logos/1018.svg", width: 512, height: 511, institution: "Bayburt Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Bayburt_University_logo.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "1033": { src: "/university-logos/1033.svg", width: 210, height: 137, institution: "Düzce Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:D%C3%BCzce_University_logo.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "1043": { src: "/university-logos/1043.svg", width: 512, height: 113, institution: "Tokat Gaziosmanpaşa Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Tokat_Gaziosmanpa%C5%9Fa_University_logo.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "1048": { src: "/university-logos/1048.svg", width: 100, height: 143, institution: "Hacettepe Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Hacettepe_%C3%9Cniversitesi_logo.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "1054": { src: "/university-logos/1054.svg", width: 512, height: 235, institution: "İstanbul Medeniyet Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:%C4%B0stanbul_Medeniyet_%C3%9Cniversitesi_logo.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "1062": { src: "/university-logos/1062.svg", width: 512, height: 229, institution: "Karadeniz Teknik Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Karadeniz_Technical_University_logo.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "1065": { src: "/university-logos/1065.svg", width: 512, height: 246, institution: "Abdullah Gül Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Abdullah_G%C3%BCl_University_logo.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "1071": { src: "/university-logos/1071.svg", width: 512, height: 469, institution: "Mardin Artuklu Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Mardin_Artuklu_University_logo.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "1073": { src: "/university-logos/1073.svg", width: 263, height: 90, institution: "Burdur Mehmet Akif Ersoy Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Burdur_Mehmet_Akif_Ersoy_University_logotype.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "1078": { src: "/university-logos/1078.svg", width: 512, height: 402, institution: "Muş Alparslan Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Mu%C5%9F_Alparslan_%C3%9Cniversitesi_logo.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "1083": { src: "/university-logos/1083.svg", width: 512, height: 647, institution: "Ordu Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Ordu_University_logo.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "1084": { src: "/university-logos/1084.svg", width: 480, height: 400, institution: "Orta Doğu Teknik Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Logo_ODT%C3%9C.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "1088": { src: "/university-logos/1088.svg", width: 512, height: 694, institution: "Sakarya Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Sakarya_University_logo.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "1095": { src: "/university-logos/1095.svg", width: 512, height: 251, institution: "Munzur Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Munzur_University_logo.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "1096": { src: "/university-logos/1096.jpg", width: 350, height: 200, institution: "Türk-Alman Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Logo_T%C3%BCrk_Alman_%C3%9Cniversitesi.jpg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "1104": { src: "/university-logos/1104.png", width: 1712, height: 376, institution: "Adana Alparslan Türkeş Bilim ve Teknoloji Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Adana_Alparslan_T%C3%BCrke%C5%9F_%C3%9Cniversitesi_logo.png",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "1111": { src: "/university-logos/1111.png", width: 1271, height: 432, institution: "İzmir Demokrasi Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:%C4%B0zmir_Demokrasi_%C3%9Cniversitesi.png",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "1115": { src: "/university-logos/1115.svg", width: 512, height: 455, institution: "Malatya Turgut Özal Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Malatya_Turgut_%C3%96zal_%C3%9Cniversitesi_logo.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "1117": { src: "/university-logos/1117.svg", width: 512, height: 394, institution: "Ankara Hacı Bayram Veli Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Ankara_Hac%C4%B1_Bayram_Veli_University_logo_(vertical_tr).svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "1120": { src: "/university-logos/1120.svg", width: 512, height: 548, institution: "Tarsus Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Tarsus_%C3%9Cniversitesi_logo.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "1124": { src: "/university-logos/1124.svg", width: 307, height: 136, institution: "Eskişehir Teknik Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Eski%C5%9Fehir_Technical_University_logo.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "1129": { src: "/university-logos/1129.svg", width: 512, height: 325, institution: "İzmir Bakırçay Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Bak%C4%B1r%C3%A7ay_%C3%9Cniversitesi_logo.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "2002": { src: "/university-logos/2002.svg", width: 512, height: 315, institution: "Atılım Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:At%C4%B1l%C4%B1m_%C3%9Cniversitesi_logo.svg",
    terms: "Wikimedia Commons PD shape (public domain; no attribution required). Institution trademark: identification use only." },
  "2006": { src: "/university-logos/2006.svg", width: 512, height: 450, institution: "Başkent Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Ba%C5%9Fkent_%C3%9Cniversitesi_logo.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "2008": { src: "/university-logos/2008.svg", width: 618, height: 178, institution: "Beykoz Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Beykoz_University_logo.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "2014": { src: "/university-logos/2014.svg", width: 176, height: 82, institution: "Fatih Sultan Mehmet Vakıf Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Fatih_Sultan_Mehmet_University_logo.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "2019": { src: "/university-logos/2019.svg", width: 512, height: 611, institution: "Haliç Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Hali%C3%A7_University_logo_(2022).svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "2021": { src: "/university-logos/2021.png", width: 250, height: 67, institution: "Bilkent Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Bilkentlogo.png",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "2022": { src: "/university-logos/2022.svg", width: 512, height: 511, institution: "İstanbul 29 Mayıs Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:%C4%B0stanbul_29_May%C4%B1s_%C3%9Cniversitesi_logo.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "2025": { src: "/university-logos/2025.svg", width: 512, height: 116, institution: "İstanbul Bilgi Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:%C4%B0stanbul_Bilgi_%C3%9Cniversitesi_logo.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "2035": { src: "/university-logos/2035.png", width: 1500, height: 453, institution: "İzmir Ekonomi Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:%C4%B0zmir_Ekonomi_%C3%9Cniversitesi_logo.png",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "2039": { src: "/university-logos/2039.svg", width: 225, height: 48, institution: "Koç Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Ko%C3%A7_University_logo.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "2048": { src: "/university-logos/2048.svg", width: 531, height: 158, institution: "Özyeğin Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:%C3%96zye%C4%9Fin_University_logo.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "2050": { src: "/university-logos/2050.svg", width: 328, height: 112, institution: "İstanbul Topkapı Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:%C4%B0stanbul_Topkap%C4%B1_%C3%9Cniversitesi_logo.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "2051": { src: "/university-logos/2051.svg", width: 139, height: 60, institution: "Sabancı Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Sabanc%C4%B1_University_logo.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "2064": { src: "/university-logos/2064.svg", width: 512, height: 318, institution: "Antalya Bilim Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Antalya_Bilim_%C3%9Cniversitesi_logo.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "2076": { src: "/university-logos/2076.svg", width: 131, height: 73, institution: "Biruni Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Biruni_%C3%9Cniversitesi_logo.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "2077": { src: "/university-logos/2077.svg", width: 512, height: 703, institution: "Sanko Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Sanko_%C3%9Cniversitesi_logo.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "2084": { src: "/university-logos/2084.svg", width: 632, height: 151, institution: "İstinye Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:%C4%B0stinye_%C3%9Cniversitesi_logo.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "2086": { src: "/university-logos/2086.svg", width: 512, height: 333, institution: "İbn Haldun Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:%C4%B0bn_Haldun_%C3%9Cniversitesi_logo.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "2088": { src: "/university-logos/2088.svg", width: 512, height: 329, institution: "Lokman Hekim Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Lokman_Hekim_%C3%9Cniversitesi_logo.svg",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "2094": { src: "/university-logos/2094.png", width: 300, height: 143, institution: "İstanbul Sağlık ve Teknoloji Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:%C4%B0stanbul_Sa%C4%9Fl%C4%B1k_ve_Teknoloji_%C3%9Cniversitesi_logo.png",
    terms: "Wikimedia Commons PD-textlogo (public domain; no attribution required). Institution trademark: identification use only." },
  "2095": { src: "/university-logos/2095.png", width: 600, height: 600, institution: "Ankara Bilim Üniversitesi",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Ankara_Bilim_%C3%9Cniversitesi_Kurumsal_Logo.png",
    terms: "Wikimedia Commons PD shape (public domain; no attribution required). Institution trademark: identification use only." },
});

/** The verified logo for an institution code, or null (the UI then shows the neutral fallback). */
export function logoFor(code: string | null | undefined, registry: Readonly<Record<string, LogoAsset>> = VERIFIED_LOGOS): LogoAsset | null {
  if (!code) return null;
  return registry[code] ?? null;
}
