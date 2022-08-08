import Project from "../models/project";
import Settings from "../models/settings";
import httpService from "./httpService";
import config from "../config.json";
import Source from "../models/source";
import Script from "../models/script";
import Prep from "../models/prep";
import PrepRound from "../models/prepRound";
import Dedupe from "../models/dedupe";
import ScripWithTresholds from "../models/scriptWithTresholds";
import ScriptWithLanguageScope from "../models/scriptWithLanguageScope";
import Prescreen from "../models/prescreen";
import Data from "../models/data";

const apiEndpoint = config.apiEndpoint + "/api";

let settingsFile: any = {};

const getSettings = async (): Promise<Settings> => {
  const response = await httpService.get(`${apiEndpoint}/getSettings`);

  settingsFile = response.data;

  const settings = new Settings();

  settings.project = new Project();
  projectFromSettings(settings.project, settingsFile.project);

  for (const s of settingsFile.sources) {
    const source = new Source();
    sourceFromSettings(source, s);
    settings.sources.push(source);
  }

  settings.prep = new Prep();
  prepFromSettings(settings.prep, settingsFile.prep);

  settings.dedupe = new Dedupe();
  dedupeFromSettings(settings.dedupe, settingsFile.dedupe);

  settings.prescreen = new Prescreen();
  prescreenFromSettings(settings.prescreen, settingsFile.prescreen);

  settings.data = new Data();
  dataFromSettings(settings.data, settingsFile.data);

  return Promise.resolve<Settings>(settings);
};

const saveSettings = async (settings: Settings): Promise<void> => {
  const newSettingsFile = {
    ...settingsFile,
    project: projectToSettings(settings.project),
    sources: [],
    prep: prepToSettings(settings.prep),
    dedupe: dedupeToSettings(settings.dedupe),
    prescreen: prescreenToSettings(settings.prescreen),
    data: dataToSettings(settings.data),
  };

  for (const source of settings.sources) {
    const settingsFileSource = sourceToSettings(source);
    newSettingsFile.sources.push(settingsFileSource);
  }

  await httpService.post(`${apiEndpoint}/saveSettings`, newSettingsFile, {
    headers: { "content-type": "application/json" },
  });

  return Promise.resolve();
};

const projectFromSettings = (project: Project, settingsProject: any) => {
  project.reviewType = settingsProject.review_type;
  project.idPattern = settingsProject.id_pattern;
  project.shareStatReq = settingsProject.share_stat_req;
  project.delayAutomatedProcessing = settingsProject.delay_automated_processing;
  project.curationUrl = settingsProject.curation_url;
  project.curatedMasterdata = settingsProject.curated_masterdata;
  project.curatedFields = settingsProject.curated_fields;
};

const projectToSettings = (project: Project): any => {
  const settingsFileProject = {
    ...settingsFile.project,
    review_type: project.reviewType,
    id_pattern: project.idPattern,
    share_stat_req: project.shareStatReq,
    delay_automated_processing: project.delayAutomatedProcessing,
    curation_url: project.curationUrl,
    curated_masterdata: project.curatedMasterdata,
    curated_fields: project.curatedFields,
  };
  return settingsFileProject;
};

const sourceFromSettings = (source: Source, settingsSource: any) => {
  source.filename = settingsSource.filename;
  source.searchType = settingsSource.search_type;
  source.sourceName = settingsSource.source_name;
  source.sourceIdentifier = settingsSource.source_identifier;
  source.searchParameters = settingsSource.search_parameters;

  source.searchScript.endpoint = settingsSource.search_script.endpoint;
  source.conversionScript.endpoint = settingsSource.conversion_script.endpoint;

  source.sourcePrepScripts = scriptsFromSettings(
    settingsSource.source_prep_scripts
  );

  source.comment = settingsSource.comment;
};

const sourceToSettings = (source: Source): any => {
  const settingsFileSource = {
    filename: source.filename,
    search_type: source.searchType,
    source_name: source.sourceName,
    source_identifier: source.sourceIdentifier,
    search_parameters: source.searchParameters,

    search_script: {
      endpoint: source.searchScript.endpoint,
    },
    conversion_script: {
      endpoint: source.conversionScript.endpoint,
    },
    source_prep_scripts: scriptsToSettings(source.sourcePrepScripts),
    comment: source.comment,
  };

  return settingsFileSource;
};

const prepFromSettings = (prep: Prep, settingsPrep: any) => {
  prep.fieldsToKeep = settingsPrep.fields_to_keep;

  for (const p of settingsPrep.prep_rounds) {
    const prepRound = new PrepRound();
    prepRound.name = p.name;
    prepRound.similarity = p.similarity;
    prepRound.scripts = scriptsFromSettings(p.scripts);
    prep.prepRounds.push(prepRound);
  }

  prep.manPrepScripts = scriptsFromSettings(settingsPrep.man_prep_scripts);
};

const prepToSettings = (prep: Prep): any => {
  const settingsFilePrep = {
    ...settingsFile.prep,
    fields_to_keep: prep.fieldsToKeep,
    prep_rounds: [],
    man_prep_scripts: scriptsToSettings(prep.manPrepScripts),
  };

  for (const p of prep.prepRounds) {
    const prep_round = {
      name: p.name,
      similarity: p.similarity,
      scripts: scriptsToSettings(p.scripts),
    };

    settingsFilePrep.prep_rounds.push(prep_round);
  }

  return settingsFilePrep;
};

const scriptsFromSettings = (settingsScripts: any) => {
  const scripts: Script[] = [];

  for (const settingsScript of settingsScripts) {
    if ("merge_threshold" in settingsScript) {
      const script = new ScripWithTresholds();
      script.endpoint = settingsScript.endpoint;
      script.mergeTreshold = settingsScript.merge_threshold;
      script.partitionTreshold = settingsScript.partition_threshold;
      scripts.push(script);
    } else if ("LanguageScope" in settingsScript) {
      const script = new ScriptWithLanguageScope();
      script.endpoint = settingsScript.endpoint;
      script.languageScope = settingsScript.LanguageScope;
      scripts.push(script);
    } else {
      const script = new Script();
      script.endpoint = settingsScript.endpoint;
      scripts.push(script);
    }
  }

  return scripts;
};

const scriptsToSettings = (scripts: Script[]) => {
  const settingsScripts: any[] = [];

  for (const script of scripts) {
    if (script instanceof ScripWithTresholds) {
      const settingsScript = {
        endpoint: script.endpoint,
        merge_threshold: script.mergeTreshold,
        partition_threshold: script.partitionTreshold,
      };
      settingsScripts.push(settingsScript);
    } else if (script instanceof ScriptWithLanguageScope) {
      const settingsScript = {
        endpoint: script.endpoint,
        LanguageScope: script.languageScope,
      };
      settingsScripts.push(settingsScript);
    } else {
      const settingsScript = {
        endpoint: script.endpoint,
      };
      settingsScripts.push(settingsScript);
    }
  }

  return settingsScripts;
};

const dedupeFromSettings = (dedupe: Dedupe, settingsDedupe: any) => {
  dedupe.sameSourceMerges = settingsDedupe.same_source_merges;
  dedupe.scripts = scriptsFromSettings(settingsDedupe.scripts);
};

const dedupeToSettings = (dedupe: Dedupe): any => {
  const settingsDedupe = {
    same_source_merges: dedupe.sameSourceMerges,
    scripts: scriptsToSettings(dedupe.scripts),
  };

  return settingsDedupe;
};

const prescreenFromSettings = (
  prescreen: Prescreen,
  settingsPrescreen: any
) => {
  prescreen.explanation = settingsPrescreen.explanation;
  prescreen.scripts = scriptsFromSettings(settingsPrescreen.scripts);
};

const prescreenToSettings = (prescreen: Prescreen): any => {
  const settingsPrescreen = {
    explanation: prescreen.explanation,
    scripts: scriptsToSettings(prescreen.scripts),
  };

  return settingsPrescreen;
};

const dataFromSettings = (data: Data, settingsData: any) => {
  data.scripts = scriptsFromSettings(settingsData.scripts);
};

const dataToSettings = (data: Data): any => {
  const settingsData = {
    scripts: scriptsToSettings(data.scripts),
  };

  return settingsData;
};

const dataService = {
  getSettings,
  saveSettings,
};

export default dataService;