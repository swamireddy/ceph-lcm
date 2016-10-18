import * as _ from 'lodash';
import { Record } from 'js-data';
import { Component, ViewChild } from '@angular/core';
import { Router } from '@angular/router';
import { Modal, Filter } from '../directives';
import { DataService } from '../services/data';
import { Cluster, Server, Playbook, PlaybookConfiguration, Execution } from '../models';
import { WizardComponent } from './wizard';

@Component({
  templateUrl: './app/templates/configurations.html'
})
export class ConfigurationsComponent {

  configurations: PlaybookConfiguration[] = null;
  clusters: Cluster[] = [];
  playbooks: Playbook[] = [];
  servers: Server[] = [];
  shownConfiguration: PlaybookConfiguration = null;
  configurationVersions: {[key: string]: PlaybookConfiguration[]} = {};
  clone: PlaybookConfiguration = null;
  @ViewChild(WizardComponent) wizard: WizardComponent;
  @ViewChild(Filter) filter: Filter;

  constructor(
    private data: DataService,
    private modal: Modal,
    private router: Router
  ) {
    this.fetchData();
    this.data.playbook().findAll({})
      .then((playbooks: Playbook[]) => {
        this.playbooks = playbooks;
      })
  }

  getPlaybooksForFilter(): Object[] {
    return _.map(this.playbooks, (playbook: Playbook) => {
      return [playbook.name, playbook.id];
    });
  }

  fetchData() {
    this.data.configuration().findAll({filter: _.get(this.filter, 'query', {})})
      .then(
        (configurations: PlaybookConfiguration[]) => this.configurations = configurations,
        (error: any) => this.data.handleResponseError(error)
      );
  }

  editConfiguration(configuration: PlaybookConfiguration = null) {
    this.clone = configuration;
    Promise.all([
      this.data.cluster().findAll({})
        .then((clusters: Cluster[]) => this.clusters = clusters),
      this.data.playbook().findAll({})
        .then((playbooks: Playbook[]) => this.playbooks = playbooks),
      this.data.server().findAll({})
        .then((servers: Server[]) => this.servers = servers)
    ]).catch((error: any) => this.data.handleResponseError(error));
    this.wizard.init(configuration);
    this.modal.show();
  }

  refreshConfigurations() {
    if (this.shownConfiguration) {
      this.getConfigurationVersions(this.shownConfiguration, true);
    } else {
      this.fetchData();
    }
  }

  isCurrent(configuration: PlaybookConfiguration) {
    return this.shownConfiguration && this.shownConfiguration.id === configuration.id;
  }

  showVersions(configuration: PlaybookConfiguration) {
    this.shownConfiguration = this.isCurrent(configuration) ? null : configuration;
  }

  getConfigurationVersions(configuration: PlaybookConfiguration, reread: boolean = false) {
    if (!this.configurationVersions[configuration.id] || reread) {
      this.data.configuration().getVersions(configuration.id)
        .then(
          (versions: PlaybookConfiguration[]) => {
            this.configurationVersions[configuration.id] = versions;
          },
          (error: any) => this.data.handleResponseError(error)
        );
      this.configurationVersions[configuration.id] = [];
    }
    return this.configurationVersions[configuration.id];
  }

  executeConfiguration(version: PlaybookConfiguration) {
    this.data.execution().postCreate(
      new Record({playbook_configuration: {id: version.id, version: version.version}})
    ). then(
      () => this.router.navigate(['/executions']),
      (error: any) => this.data.handleResponseError(error)
    );
  }
}